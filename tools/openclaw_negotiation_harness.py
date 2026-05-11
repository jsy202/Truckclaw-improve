#!/usr/bin/env python3
"""Deterministic OpenClaw negotiation harness for platoon transfers.

This exercises the same bridge contract the OpenClaw agents use:
candidate discovery -> request -> responder validation -> accept -> commit.
It does not drive CARLA directly; after commit, CARLA/scenario must report
physical progress back through the bridge.
"""

import argparse
import json
import sys
import time
from urllib import error, parse, request


ACTIVE_STATUSES = {"pending", "accepted", "committed", "splitting", "merging"}
FINAL_STATUSES = {"carla_complete", "merge_failed", "trigger_failed", "rejected"}


def http_json(method, url, payload=None, timeout=10):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body)
        except json.JSONDecodeError:
            detail = {"error": body or exc.reason}
        raise RuntimeError(f"HTTP {exc.code}: {json.dumps(detail, ensure_ascii=False)}") from exc


class Bridge:
    def __init__(self, base_url):
        self.base = base_url.rstrip("/")

    def get(self, path):
        return http_json("GET", f"{self.base}{path}")

    def post(self, path, payload=None):
        return http_json("POST", f"{self.base}{path}", payload or {})

    def health(self):
        return self.get("/health")

    def snapshot(self):
        return self.get("/snapshot")

    def candidates(self, platoon_id):
        return self.get(f"/platoons/{parse.quote(platoon_id)}/transfer-candidates")["candidates"]

    def transfer(self, request_id):
        return self.get(f"/transfers/{parse.quote(request_id)}")


def find_member(snapshot, vehicle_id):
    for platoon_id, platoon in snapshot["platoons"].items():
        for member in platoon.get("members", []):
            if member.get("vehicle_id") == vehicle_id:
                return platoon_id, platoon, member
    return None, None, None


def assert_no_conflict(snapshot, from_platoon, to_platoon):
    for transfer in snapshot.get("transfers", {}).values():
        if transfer.get("status") not in ACTIVE_STATUSES:
            continue
        if transfer.get("from_platoon_id") in (from_platoon, to_platoon):
            raise RuntimeError(f"active transfer blocks {from_platoon}/{to_platoon}: {transfer}")
        if transfer.get("to_platoon_id") in (from_platoon, to_platoon):
            raise RuntimeError(f"active transfer blocks {from_platoon}/{to_platoon}: {transfer}")


def choose_candidate(bridge, snapshot, from_platoon, to_platoon, vehicle_id=None):
    from_state = snapshot["platoons"][from_platoon]
    to_state = snapshot["platoons"][to_platoon]
    candidates = bridge.candidates(from_platoon)

    valid = []
    for candidate in candidates:
        cid = candidate["vehicle_id"]
        owner_id, _, member = find_member(snapshot, cid)
        if owner_id != from_platoon:
            continue
        if member.get("role") == "leader" or cid.endswith("truck0"):
            continue
        if candidate.get("target_platoon_id") != to_platoon:
            continue
        if member.get("destination_id") != to_state.get("destination_id"):
            continue
        valid.append(candidate)

    if vehicle_id:
        valid = [c for c in valid if c["vehicle_id"] == vehicle_id]
    if not valid:
        raise RuntimeError(
            f"no validated follower candidate from {from_platoon} to {to_platoon}; "
            f"bridge candidates={candidates}"
        )

    valid.sort(key=lambda c: (c.get("requires_split", False), c["vehicle_id"]))
    return valid[0]


def run_negotiation(args):
    bridge = Bridge(args.base_url)
    bridge.health()
    if args.reload:
        bridge.post("/reload")

    snapshot = bridge.snapshot()
    assert_no_conflict(snapshot, args.from_platoon, args.to_platoon)
    candidate = choose_candidate(bridge, snapshot, args.from_platoon, args.to_platoon, args.vehicle_id)
    vehicle_id = candidate["vehicle_id"]

    print(f"[A] destination-compatible candidate: {vehicle_id} -> {args.to_platoon}")
    if args.dry_run:
        print("[dry-run] stopping before request")
        return 0

    created = bridge.post(
        "/transfers",
        {
            "vehicle_id": vehicle_id,
            "from_platoon_id": args.from_platoon,
            "to_platoon_id": args.to_platoon,
            "reason": "destination_match",
            "sender_agent": args.from_platoon,
            "receiver_agent": args.to_platoon,
        },
    )
    request_id = created["request_id"]
    print(f"request_id: {request_id}")
    print("status: pending")

    pending = bridge.transfer(request_id)
    if pending.get("status") != "pending":
        raise RuntimeError(f"expected pending transfer, got {pending}")
    snapshot = bridge.snapshot()
    assert_no_conflict(
        {"transfers": {k: v for k, v in snapshot["transfers"].items() if k != request_id}},
        args.from_platoon,
        args.to_platoon,
    )
    owner_id, _, member = find_member(snapshot, vehicle_id)
    if owner_id != args.from_platoon or member is None:
        raise RuntimeError(f"{vehicle_id} is no longer in {args.from_platoon}")

    accepted = bridge.post(
        f"/transfers/{request_id}/accept",
        {
            "reason": "destination_match_confirmed",
            "sender_agent": args.to_platoon,
            "receiver_agent": args.from_platoon,
        },
    )
    print(f"status: {accepted['status']}")

    committed = bridge.post(f"/transfers/{request_id}/commit", {})
    print(f"status: {committed['status']}")

    if args.wait_complete:
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            current = bridge.transfer(request_id)
            print(f"[wait] status: {current['status']}")
            if current["status"] in FINAL_STATUSES:
                return 0 if current["status"] == "carla_complete" else 2
            time.sleep(args.poll_interval)
        raise RuntimeError(f"timed out waiting for physical completion: {bridge.transfer(request_id)}")

    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="Run a deterministic OpenClaw bridge negotiation.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18801")
    parser.add_argument("--from-platoon", default="platoon_a")
    parser.add_argument("--to-platoon", default="platoon_b")
    parser.add_argument("--vehicle-id")
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--wait-complete", action="store_true")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    return parser


def main():
    try:
        return run_negotiation(build_parser().parse_args())
    except Exception as exc:
        print(f"[harness:error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
