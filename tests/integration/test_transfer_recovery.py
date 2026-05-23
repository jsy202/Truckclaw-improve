"""Dependency-failure, recovery and preserved-behavior regression tests.

These were written after the DEF-01..11 fixes and pass on the fixed bridge.
Tests marked "(baseline: also passes)" pin behavior that was already correct
at research-baseline; the rest exercise paths introduced by the fixes.
"""

import time

import platoon_bridge_server as bridge
from fakes.fake_carla import FakeCarlaScenario

VEHICLE = "platoon_a_truck1"
FROM, TO = "platoon_a", "platoon_b"
ORIGINAL_A = ["platoon_a_truck0", "platoon_a_truck1", "platoon_a_truck2"]
ORIGINAL_B = ["platoon_b_truck0", "platoon_b_truck1", "platoon_b_truck2"]


def _request(client, vehicle=VEHICLE):
    status, t = client.post("/transfers", {"vehicle_id": vehicle, "from_platoon_id": FROM, "to_platoon_id": TO})
    assert status == 200, t
    return t["request_id"]


def _commit(client, rid):
    assert client.post(f"/transfers/{rid}/accept")[0] == 200
    assert client.post(f"/transfers/{rid}/commit")[0] == 200


def _use_fake(client, monkeypatch, **kw):
    fake = FakeCarlaScenario(client.base_url, **kw).start()
    monkeypatch.setattr(bridge, "CARLA_TRIGGER_URL", fake.trigger_url)
    return fake


# ── dependency failure ───────────────────────────────────────────────────────

def test_trigger_non_2xx_response_marks_trigger_failed(client, monkeypatch):
    fake = _use_fake(client, monkeypatch, mode="bad_response")
    try:
        rid = _request(client)
        _commit(client, rid)
        client.wait_for_status(rid, "trigger_failed")
        assert "500" in client.transfer(rid)["reason"]
        assert client.members(FROM) == ORIGINAL_A
    finally:
        fake.stop()


def test_carla_failure_report_marks_merge_failed_and_keeps_membership(client, monkeypatch):
    # (baseline: also passes)
    fake = _use_fake(client, monkeypatch, mode="fail")
    try:
        rid = _request(client)
        _commit(client, rid)
        client.wait_for_status(rid, "merge_failed")
        assert client.transfer(rid)["reason"] == "fake carla failure"
        assert client.members(FROM) == ORIGINAL_A and client.members(TO) == ORIGINAL_B
    finally:
        fake.stop()


def test_partial_failure_after_split_keeps_membership_and_releases_platoons(client, monkeypatch):
    # (baseline: also passes)
    fake = _use_fake(client, monkeypatch, mode="partial")
    try:
        rid = _request(client)
        _commit(client, rid)
        client.wait_for_status(rid, "merge_failed")
        assert [step for _, step, _ in fake.reports] == ["splitting", "merging", "failed"]
        assert client.members(FROM) == ORIGINAL_A and client.members(TO) == ORIGINAL_B
        # A failed transfer is no longer active, so a new request is possible.
        assert client.post("/transfers", {"vehicle_id": "platoon_a_truck2", "from_platoon_id": FROM, "to_platoon_id": TO})[0] == 200
    finally:
        fake.stop()


def test_delayed_progress_within_timeout_is_not_timed_out(client, monkeypatch):
    # Timeout only covers "no CARLA progress at all"; slow but progressing maneuvers complete.
    monkeypatch.setattr(bridge, "TRANSFER_TIMEOUT_S", 0.5)
    fake = _use_fake(client, monkeypatch, mode="complete", step_delay_s=0.3)
    try:
        rid = _request(client)
        _commit(client, rid)
        client.wait_for_status(rid, "carla_complete", timeout=3.0)
        assert client.members(TO)[-1] == VEHICLE
    finally:
        fake.stop()


# ── recovery ─────────────────────────────────────────────────────────────────

def test_retry_after_trigger_failure_completes_transfer(client, unreachable_trigger, monkeypatch):
    rid = _request(client)
    _commit(client, rid)
    client.wait_for_status(rid, "trigger_failed")
    fake = _use_fake(client, monkeypatch, mode="complete")  # CARLA side comes back
    try:
        status, t = client.post(f"/transfers/{rid}/retry")
        assert status == 200 and t["status"] == "committed"
        client.wait_for_status(rid, "carla_complete")
        assert fake.trigger_count() == 1
        assert client.members(TO)[-1] == VEHICLE
    finally:
        fake.stop()


def test_late_carla_progress_after_trigger_failure_is_accepted(client, unreachable_trigger):
    # Scenario polls /snapshot and may act even if the trigger POST failed;
    # real physical progress must not be rejected.
    rid = _request(client)
    _commit(client, rid)
    client.wait_for_status(rid, "trigger_failed")
    for step in ("splitting", "merging", "carla_complete"):
        assert client.post(f"/transfers/{rid}/{step}")[0] == 200
    assert client.members(TO)[-1] == VEHICLE


def test_timed_out_transfer_can_be_retried(client, monkeypatch):
    monkeypatch.setattr(bridge, "TRANSFER_TIMEOUT_S", 0.3)
    fake = _use_fake(client, monkeypatch, mode="silent")
    try:
        rid = _request(client)
        _commit(client, rid)
        client.wait_for_status(rid, "merge_failed", timeout=2.0)
        fake.mode = "complete"
        assert client.post(f"/transfers/{rid}/retry")[0] == 200
        client.wait_for_status(rid, "carla_complete")
    finally:
        fake.stop()


# ── state machine: permitted paths still work ────────────────────────────────

def test_reject_from_accepted_is_allowed(client):
    # (baseline: also passes)
    rid = _request(client)
    assert client.post(f"/transfers/{rid}/accept")[0] == 200
    status, t = client.post(f"/transfers/{rid}/reject")
    assert status == 200 and t["status"] == "rejected"


def test_new_request_replaces_pending_request_for_same_vehicle(client):
    # (baseline: also passes) existing takeover behavior is preserved.
    first = _request(client)
    second = _request(client)
    assert first != second
    assert client.transfer(first)["status"] == "replaced"
    assert client.transfer(second)["status"] == "pending"


def test_second_transfer_on_busy_platoon_is_rejected(client, fake_carla):
    # (baseline: also passes)
    fake_carla.hold.set()
    rid = _request(client)
    _commit(client, rid)
    status, _ = client.post("/transfers", {"vehicle_id": "platoon_a_truck2", "from_platoon_id": FROM, "to_platoon_id": TO})
    assert status == 409


def test_unknown_request_id_on_action_returns_404(client):
    # (baseline: also passes for these actions)
    for action in ("accept", "reject", "commit", "retry", "splitting", "merging", "carla_complete"):
        assert client.post(f"/transfers/tr_missing/{action}")[0] == 404, action


# ── existing MOCK_CARLA mode is preserved ───────────────────────────────────

def test_existing_mock_carla_mode_still_completes(client, monkeypatch):
    # (baseline: also passes) MOCK_CARLA=true path sets statuses directly with 2 s sleeps.
    monkeypatch.setattr(bridge, "MOCK_MODE", True)
    rid = _request(client)
    _commit(client, rid)
    client.wait_for_status(rid, "carla_complete", timeout=8.0)
    assert client.members(TO)[-1] == VEHICLE
