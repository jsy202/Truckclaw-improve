"""Regression tests for bridge defects reproduced against research-baseline (3a9788f).

Each test asserts the *required* behavior. Tests that fail on the current code
are marked xfail(strict=True): when a fix lands, the test XPASSes, strict mode
turns that into a failure, and the fix commit must remove the marker.

Defect IDs (DEF-xx) match the validation report. One defect per test.
"""

import time

import pytest

import platoon_bridge_server as bridge
from fakes.fake_carla import FakeCarlaScenario

VEHICLE = "platoon_a_truck1"
FROM, TO = "platoon_a", "platoon_b"


def _request(client, vehicle=VEHICLE, from_p=FROM, to_p=TO):
    status, t = client.post("/transfers", {"vehicle_id": vehicle, "from_platoon_id": from_p, "to_platoon_id": to_p})
    assert status == 200, t
    return t["request_id"]


def _committed(client, fake=None):
    rid = _request(client)
    assert client.post(f"/transfers/{rid}/accept")[0] == 200
    if fake is not None:
        fake.hold.set()
    assert client.post(f"/transfers/{rid}/commit")[0] == 200
    return rid


def _wait_triggers(fake, n, timeout=2.0):
    deadline = time.monotonic() + timeout
    while fake.trigger_count() < n and time.monotonic() < deadline:
        time.sleep(0.01)


# ── Input validation ─────────────────────────────────────────────────────────

def test_rejects_unknown_vehicle_id(client):
    # REQ: a transfer may only be created for a vehicle that is a member of from_platoon_id.
    status, body = client.post("/transfers", {"vehicle_id": "ghost_truck9", "from_platoon_id": FROM, "to_platoon_id": TO})
    assert status in (400, 404), body
    assert client.snapshot()["transfers"] == {}


def test_rejects_unknown_platoon_id(client):
    # REQ: invalid input must produce an explicit HTTP error, never a dropped connection.
    status, body = client.post("/transfers", {"vehicle_id": VEHICLE, "from_platoon_id": "platoon_x", "to_platoon_id": TO})
    assert status in (400, 404), body
    assert "error" in body


def test_rejects_non_object_json_body(client):
    # REQ: a malformed payload must be rejected with 400, not crash the request handler.
    status, body = client.post("/transfers", [1, 2])
    assert status == 400, body


def test_failed_unknown_request_returns_error(client):
    # REQ: every endpoint must answer an unknown request_id with an explicit 404.
    status, body = client.post("/transfers/tr_doesnotexist/failed", {"reason": "x"})
    assert status == 404, body


# ── State transitions ────────────────────────────────────────────────────────

def test_commit_requires_accepted_state(client, fake_carla):
    # REQ: commit is only valid from 'accepted'; physical execution needs the receiver's acceptance.
    rid = _request(client)
    status, _ = client.post(f"/transfers/{rid}/commit")
    assert status == 409
    assert client.transfer(rid)["status"] == "pending"
    time.sleep(0.2)
    assert fake_carla.trigger_count() == 0


def test_duplicate_commit_does_not_retrigger_carla(client, fake_carla):
    # REQ: the same request_id must be executed at most once (idempotent commit).
    rid = _committed(client, fake_carla)
    _wait_triggers(fake_carla, 1)
    status, body = client.post(f"/transfers/{rid}/commit")
    assert status == 200 and body["status"] == "committed"  # idempotent: current state returned
    _wait_triggers(fake_carla, 2, timeout=0.5)
    assert fake_carla.trigger_count() == 1


def test_carla_complete_requires_valid_state(client):
    # REQ: logical completion must follow physical execution (committed/splitting/merging only).
    rid = _request(client)
    before_from, before_to = client.members(FROM), client.members(TO)
    status, _ = client.post(f"/transfers/{rid}/carla_complete")
    assert status == 409
    assert client.members(FROM) == before_from
    assert client.members(TO) == before_to


def test_completed_transfer_cannot_regress_to_accepted(client, fake_carla):
    # REQ: terminal states (carla_complete) must not transition back to earlier states.
    rid = _committed(client)
    client.wait_for_status(rid, "carla_complete")
    status, _ = client.post(f"/transfers/{rid}/accept")
    assert status == 409
    assert client.transfer(rid)["status"] == "carla_complete"


# ── Failure propagation / recovery ───────────────────────────────────────────

@pytest.mark.xfail(strict=True, reason="DEF-09: trigger POST failure only updates readiness; transfer stays 'committed' (trigger_failed never set)")
def test_trigger_failure_updates_transfer_state(client, unreachable_trigger):
    # REQ: a failed CARLA trigger must be reflected on the transfer as 'trigger_failed'.
    rid = _committed(client)
    client.wait_for_status(rid, "trigger_failed", timeout=4.0)


@pytest.mark.xfail(strict=True, reason="DEF-10: after a trigger failure the platoon stays locked (409) until /reload")
def test_trigger_failure_does_not_permanently_block_platoon(client, unreachable_trigger):
    # REQ: a failed transfer must release the platoons so a new request can be made.
    _committed(client)
    deadline = time.monotonic() + 4.0
    status = None
    while time.monotonic() < deadline:
        status, _ = client.post("/transfers", {"vehicle_id": "platoon_a_truck2", "from_platoon_id": FROM, "to_platoon_id": TO})
        if status == 200:
            break
        time.sleep(0.1)
    assert status == 200


@pytest.mark.xfail(strict=True, reason="DEF-11: no transfer timeout exists; committed transfer with no CARLA progress waits forever")
def test_transfer_times_out(client, monkeypatch):
    # REQ: a committed transfer with no physical progress must end in a failure state after a bounded time.
    # TRANSFER_TIMEOUT_S does not exist in the current bridge. It is the proposed
    # configuration point, set short here so the test runs fast.
    monkeypatch.setattr(bridge, "TRANSFER_TIMEOUT_S", 0.5, raising=False)
    fake = FakeCarlaScenario(client.base_url, mode="silent").start()
    monkeypatch.setattr(bridge, "CARLA_TRIGGER_URL", fake.trigger_url)
    try:
        rid = _committed(client)
        client.wait_for_status(rid, bridge.FAILURE_TRANSFER_STATUSES, timeout=2.5)
    finally:
        fake.stop()
