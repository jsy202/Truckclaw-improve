"""Happy-path integration test: negotiation -> trigger -> fake CARLA progress -> logical transfer.

Path under test (production code unchanged):
    test client -> Bridge REST -> HTTP trigger -> FakeCarlaScenario -> Bridge progress callbacks
"""

VEHICLE = "platoon_a_truck1"
FROM, TO = "platoon_a", "platoon_b"


def test_transfer_completes_end_to_end(client, fake_carla):
    # 1. Candidate discovery finds the destination-mismatched follower.
    status, body = client.get(f"/platoons/{FROM}/transfer-candidates")
    assert status == 200
    assert {"vehicle_id": VEHICLE, "target_platoon_id": TO, "requires_split": True} in body["candidates"]

    # 2. Request -> accept.
    status, t = client.post("/transfers", {"vehicle_id": VEHICLE, "from_platoon_id": FROM, "to_platoon_id": TO})
    assert status == 200
    assert t["status"] == "pending"
    assert t["requires_split"] is True
    rid = t["request_id"]

    status, t = client.post(f"/transfers/{rid}/accept")
    assert status == 200 and t["status"] == "accepted"

    # 3. Commit while the fake holds physical progress:
    #    HTTP 200 on commit means "accepted for execution", not "transfer done".
    fake_carla.hold.set()
    status, t = client.post(f"/transfers/{rid}/commit")
    assert status == 200 and t["status"] == "committed"
    assert VEHICLE in client.members(FROM)
    assert VEHICLE not in client.members(TO)

    # 4. Release the fake CARLA side and wait for physical completion.
    fake_carla.release()
    client.wait_for_status(rid, "carla_complete")

    # 5. Logical membership moved exactly once, to the tail of the receiver.
    assert client.members(FROM) == ["platoon_a_truck0", "platoon_a_truck2"]
    assert client.members(TO) == ["platoon_b_truck0", "platoon_b_truck1", "platoon_b_truck2", VEHICLE]
    receiver = client.get(f"/platoons/{TO}")[1]
    assert receiver["members"][-1]["role"] == "follower"
    donor = client.get(f"/platoons/{FROM}")[1]
    assert donor["members"][0]["role"] == "leader"

    # 6. Contract with the CARLA side: one trigger carrying the request_id,
    #    and every progress callback accepted by the bridge.
    assert fake_carla.triggers == [{"request_id": rid}]
    assert [(r, step, code) for r, step, code in fake_carla.reports] == [
        (rid, "splitting", 200),
        (rid, "merging", 200),
        (rid, "carla_complete", 200),
    ]
