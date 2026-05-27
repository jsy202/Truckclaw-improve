#!/usr/bin/env python3
"""
Platoon Bridge Server  –  port 18801

REST API used by platoon_bridge_ctl.py (inside Docker agents) to negotiate
vehicle transfers between platoon A and platoon B.
"""

import json
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import copy

CARLA_TRIGGER_URL = os.environ.get("CARLA_TRIGGER_URL", "http://127.0.0.1:18802/start_merge")
ACTIVE_TRANSFER_STATUSES = ("pending", "accepted", "committed", "merging", "splitting")
FAILURE_TRANSFER_STATUSES = ("trigger_failed", "merge_failed")
COMMITTED_OR_LATER_STATUSES = ("committed", "splitting", "merging", "carla_complete")
# Transfer state machine: action -> statuses it may be applied from (see validation/state_machine.md).
ALLOWED_FROM = {
    "accept":         ("pending",),
    "reject":         ("pending", "accepted"),
    "commit":         ("accepted",),
    "retry":          ("committed",) + FAILURE_TRANSFER_STATUSES,
    # trigger_failed means "trigger delivery unconfirmed": the scenario polls /snapshot and may
    # still report real physical progress, which must not be rejected.
    "splitting":      ("committed", "trigger_failed"),
    "merging":        ("committed", "splitting", "trigger_failed"),
    "carla_complete": ("committed", "splitting", "merging", "trigger_failed"),
    "failed":         ("committed", "splitting", "merging", "trigger_failed"),
}

def _load_transfer_timeout_s(default=120.0):
    """Reuse the existing timeouts.merge_timeout_s from config/simulation.json (no new setting)."""
    path = os.path.join(os.path.dirname(__file__), "..", "config", "simulation.json")
    try:
        with open(path, "r") as f:
            return float(json.load(f)["timeouts"]["merge_timeout_s"])
    except Exception:
        return default

# A committed transfer with no CARLA progress report within this time becomes merge_failed.
TRANSFER_TIMEOUT_S = _load_transfer_timeout_s()

DEFAULT_CONFIG_PATHS = [
    os.environ.get("PLATOON_DESTINATIONS_PATH"),
    os.path.join(os.path.dirname(__file__), "..", "platoon_destinations.json"),
    "/platoon_destinations.json",
    os.path.join(os.path.dirname(__file__), "..", "config", "platoons.json"),
]

def _load_initial_state():
    for path in [p for p in DEFAULT_CONFIG_PATHS if p]:
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    data = json.load(f)
                return data.get("platoons", data)
        except Exception as e:
            print(f"[bridge] Failed to load config from {path}: {e}")
    return {
        "platoon_a": {
            "platoon_id": "platoon_a",
            "destination_id": "dest_a",
            "status": "cruising",
            "members": [
                {"vehicle_id": "platoon_a_truck0", "role": "leader",   "destination_id": "dest_a"},
                {"vehicle_id": "platoon_a_truck1", "role": "follower", "destination_id": "dest_b"},
                {"vehicle_id": "platoon_a_truck2", "role": "follower", "destination_id": "dest_a"},
            ],
        },
        "platoon_b": {
            "platoon_id": "platoon_b",
            "destination_id": "dest_b",
            "status": "cruising",
            "members": [
                {"vehicle_id": "platoon_b_truck0", "role": "leader",   "destination_id": "dest_b"},
                {"vehicle_id": "platoon_b_truck1", "role": "follower", "destination_id": "dest_b"},
                {"vehicle_id": "platoon_b_truck2", "role": "follower", "destination_id": "dest_b"},
            ],
        },
    }

_lock = threading.Lock()
_platoons = _load_initial_state()
_transfers: dict = {}
_commit_deadlines: dict = {}  # request_id -> time.monotonic() deadline while status == committed
_timed_out: set = set()       # request_ids failed by commit timeout (late CARLA progress still accepted)
PROGRESS_ACTIONS = ("splitting", "merging", "carla_complete", "failed")

def _initial_readiness():
    return {
        "status": "idle",
        "merge_ready": False,
        "reason": "bridge reset; waiting for transfer commit",
        "metrics": {},
        "updated_at": None,
        "request_id": None,
        "vehicle_id": None,
    }

_readiness: dict = _initial_readiness()

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _find_vehicle(vehicle_id: str):
    for p in _platoons.values():
        for m in p["members"]:
            if m["vehicle_id"] == vehicle_id:
                return p, m
    return None, None

def _active_transfer_for(platoon_id: str):
    for tid, t in _transfers.items():
        if t["status"] in ACTIVE_TRANSFER_STATUSES:
            if t["from_platoon_id"] == platoon_id or t["to_platoon_id"] == platoon_id:
                return tid
    return None

def _active_transfer_for_vehicle(vehicle_id: str):
    for tid, t in _transfers.items():
        if t["status"] in ACTIVE_TRANSFER_STATUSES and t["vehicle_id"] == vehicle_id:
            return tid
    return None

def _is_tail_member(platoon: dict, vehicle_id: str) -> bool:
    return bool(platoon["members"] and platoon["members"][-1]["vehicle_id"] == vehicle_id)

def _complete_logical_transfer(t: dict):
    vehicle_id = t["vehicle_id"]
    from_platoon = _platoons[t["from_platoon_id"]]
    to_platoon = _platoons[t["to_platoon_id"]]
    member = next((m for m in from_platoon["members"] if m["vehicle_id"] == vehicle_id), None)
    if member:
        was_leader = (member["role"] == "leader")
        from_platoon["members"].remove(member)
        member["role"] = "follower"
        to_platoon["members"].append(member)

        if not from_platoon["members"]:
            from_platoon["status"] = "dissolved"
            print(f"[bridge] Platoon {t['from_platoon_id']} dissolved (0 members)")
        elif was_leader and from_platoon["members"]:
            from_platoon["members"][0]["role"] = "leader"
            print(f"[bridge] {from_platoon['members'][0]['vehicle_id']} promoted to leader of {t['from_platoon_id']}")
            
    return from_platoon, to_platoon

MOCK_MODE = os.environ.get("MOCK_CARLA", "false").lower() == "true" # Set MOCK_CARLA=true to simulate progress without CARLA

def _notify_carla_trigger(request_id: str):
    if MOCK_MODE:
        print(f"[bridge] Mock mode: CARLA trigger skipped for {request_id}. Simulating progress.")
        def _mock_progress():
            import time
            with _lock:
                t = _transfers.get(request_id)
                if not t: return
                t["status"] = "splitting"
                _readiness.update({"status": "splitting", "merge_ready": False, "reason": "Mocking gap opening"})
            
            time.sleep(2)
            with _lock:
                t = _transfers.get(request_id)
                if not t: return
                t["status"] = "merging"
                _readiness.update({"status": "merging", "merge_ready": False, "reason": "Mocking lane change"})
            
            time.sleep(2)
            with _lock:
                t = _transfers.get(request_id)
                if not t: return
                _complete_logical_transfer(t)
                t["status"] = "carla_complete"
                _readiness.update({"status": "idle", "merge_ready": True, "reason": "Mocking completed"})
                print(f"[bridge] Mock mode: Transfer {request_id} completed logically.")
        
        threading.Thread(target=_mock_progress, daemon=True).start()
        return

    def _do():
        try:
            payload = json.dumps({"request_id": request_id}).encode("utf-8")
            req = urllib.request.Request(CARLA_TRIGGER_URL, data=payload, method="POST", headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=2)
            with _lock:
                _readiness.update({
                    "status": "trigger_sent",
                    "merge_ready": False,
                    "reason": f"CARLA trigger sent to {CARLA_TRIGGER_URL}",
                    "request_id": request_id,
                    "updated_at": _now(),
                })
            print(f"[bridge] CARLA trigger sent ({request_id})")
        except Exception as e:
            with _lock:
                _readiness.update({
                    "status": "trigger_unconfirmed",
                    "merge_ready": False,
                    "reason": f"CARLA trigger POST failed: {e}",
                    "request_id": request_id,
                    "updated_at": _now(),
                })
                # Reflect the failure on the transfer so it leaves the active set (platoons are released).
                # Only a still-'committed' transfer is marked; progress already reported by CARLA wins.
                t = _transfers.get(request_id)
                if t and t["status"] == "committed":
                    t["status"] = "trigger_failed"
                    t["reason"] = f"CARLA trigger POST failed: {e}"
            print(f"[bridge] CARLA trigger failed: {e}")
    threading.Thread(target=_do, daemon=True).start()

def _start_commit_timer(request_id: str):
    _commit_deadlines[request_id] = time.monotonic() + TRANSFER_TIMEOUT_S
    _timed_out.discard(request_id)

def _expire_stale_commits():
    """Called under _lock on every request: fail committed transfers that never got CARLA progress."""
    now = time.monotonic()
    for rid, deadline in list(_commit_deadlines.items()):
        t = _transfers.get(rid)
        if not t or t["status"] != "committed":
            del _commit_deadlines[rid]
        elif now > deadline:
            t["status"] = "merge_failed"
            t["reason"] = f"timeout: no CARLA progress within {TRANSFER_TIMEOUT_S:g}s of commit"
            _timed_out.add(rid)
            del _commit_deadlines[rid]
            print(f"[bridge] Transfer {rid} timed out waiting for CARLA progress")

def _transfer_candidates(platoon_id: str) -> list:
    p = _platoons.get(platoon_id)
    if not p: return []
    platoon_dest = p["destination_id"]
    candidates = []
    tail_id = p["members"][-1]["vehicle_id"] if p["members"] else None
    for m in p["members"]:
        if m["destination_id"] == platoon_dest: continue
        for peer_id, peer in _platoons.items():
            if peer_id != platoon_id and peer["destination_id"] == m["destination_id"]:
                candidates.append({
                    "vehicle_id": m["vehicle_id"],
                    "target_platoon_id": peer_id,
                    "requires_split": m["vehicle_id"] != tail_id
                })
    return candidates

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body, indent=2).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def _ok(self, body): self._send(200, body)
    def _err(self, code, msg): self._send(code, {"error": msg})
    def _rejects_transition(self, t, action):
        """Send 409 and return True if `action` is not allowed from the transfer's current status."""
        if t["status"] in ALLOWED_FROM[action]: return False
        # A commit timeout only means "no progress seen yet"; real physical progress arriving later wins.
        if action in PROGRESS_ACTIONS and t["status"] == "merge_failed" and t["request_id"] in _timed_out:
            _timed_out.discard(t["request_id"])
            return False
        self._err(409, f"cannot {action} transfer in status {t['status']}")
        return True
    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length).decode()) if length > 0 else {}

    def do_GET(self):
        global _platoons
        p = self.path.rstrip("/")
        with _lock:
            _expire_stale_commits()
            if p == "/health": self._ok({"ok": True})
            elif p == "/snapshot": self._ok({"platoons": _platoons, "transfers": _transfers, "readiness": _readiness})
            elif p == "/readiness": self._ok(_readiness)
            elif p.startswith("/transfers/"):
                rid = p.split("/")[-1]
                t = _transfers.get(rid)
                if t: self._ok(t)
                else: self._err(404, "not found")
            elif p.startswith("/platoons/"):
                if p.endswith("/transfer-candidates"):
                    pid = p.split("/")[-2]
                    self._ok({"candidates": _transfer_candidates(pid)})
                else:
                    pid = p.split("/")[-1]
                    self._ok(_platoons.get(pid, {}))
            else: self._err(404, "not found")

    def do_POST(self):
        global _platoons, _transfers, _readiness
        p = self.path.rstrip("/")
        try: body = self._read_body()
        except: return self._err(400, "bad json")
        if not isinstance(body, dict): return self._err(400, "json body must be an object")

        with _lock:
            _expire_stale_commits()
            if p == "/readiness":
                _readiness.update(body); _readiness["updated_at"] = _now(); self._ok(_readiness)
            elif p == "/reload":
                _platoons = _load_initial_state()
                _transfers = {}
                _commit_deadlines.clear()
                _timed_out.clear()
                _readiness = _initial_readiness()
                _readiness["updated_at"] = _now()
                self._ok({"ok": True})
            elif p == "/transfers":
                vid, fp, tp = body.get("vehicle_id"), body.get("from_platoon_id"), body.get("to_platoon_id")
                if not vid or not fp or not tp: return self._err(400, "missing fields")
                if fp not in _platoons or tp not in _platoons:
                    return self._err(404, "unknown platoon")
                if not any(m["vehicle_id"] == vid for m in _platoons[fp]["members"]):
                    return self._err(404, f"vehicle {vid} is not a member of {fp}")

                active_vid = _active_transfer_for_vehicle(vid)
                if (_active_transfer_for(fp) or _active_transfer_for(tp)) and not active_vid:
                    return self._err(409, "platoon already has an active transfer")
                
                # Takeover logic for vehicle (safety check)
                if active_vid and _transfers[active_vid]["status"] in ("pending", "accepted"):
                    _transfers[active_vid]["status"] = "replaced"
                rid = "tr_" + uuid.uuid4().hex[:8]
                t = {"request_id": rid, "vehicle_id": vid, "from_platoon_id": fp, "to_platoon_id": tp, "status": "pending", "requires_split": not _is_tail_member(_platoons[fp], vid), "created_at": _now()}
                _transfers[rid] = t; self._ok(t)
            elif "/accept" in p:
                rid = p.split("/")[-2]; t = _transfers.get(rid)
                if t and self._rejects_transition(t, "accept"): pass
                elif t: t["status"] = "accepted"; self._ok(t)
                else: self._err(404, "not found")
            elif "/reject" in p:
                rid = p.split("/")[-2]; t = _transfers.get(rid)
                if t and self._rejects_transition(t, "reject"): pass
                elif t: t["status"] = "rejected"; self._ok(t)
                else: self._err(404, "not found")
            elif "/commit" in p:
                rid = p.split("/")[-2]; t = _transfers.get(rid)
                # Idempotent: a repeated commit returns the current state without re-triggering CARLA.
                if t and t["status"] in COMMITTED_OR_LATER_STATUSES: self._ok(t)
                elif t and self._rejects_transition(t, "commit"): pass
                elif t: t["status"] = "committed"; _start_commit_timer(rid); _notify_carla_trigger(rid); self._ok(t)
                else: self._err(404, "not found")
            elif "/retry" in p:
                rid = p.split("/")[-2]; t = _transfers.get(rid)
                if t and self._rejects_transition(t, "retry"): pass
                elif t: t["status"] = "committed"; _start_commit_timer(rid); _notify_carla_trigger(rid); self._ok(t)
                else: self._err(404, "not found")
            elif "/splitting" in p:
                rid = p.split("/")[-2]; t = _transfers.get(rid)
                if t and self._rejects_transition(t, "splitting"): pass
                elif t: t["status"] = "splitting"; self._ok(t)
                else: self._err(404, "not found")
            elif "/merging" in p:
                rid = p.split("/")[-2]; t = _transfers.get(rid)
                if t and self._rejects_transition(t, "merging"): pass
                elif t: t["status"] = "merging"; self._ok(t)
                else: self._err(404, "not found")
            elif "/carla_complete" in p:
                rid = p.split("/")[-2]; t = _transfers.get(rid)
                if t and self._rejects_transition(t, "carla_complete"): pass
                elif t: _complete_logical_transfer(t); t["status"] = "carla_complete"; self._ok(t)
                else: self._err(404, "not found")
            elif "/failed" in p:
                rid = p.split("/")[-2]; t = _transfers.get(rid)
                if t and self._rejects_transition(t, "failed"): pass
                elif t: t["status"] = "merge_failed"; t["reason"] = body.get("reason", "unknown"); self._ok(t)
                else: self._err(404, "not found")
            else: self._err(404, "not found")

def main():
    server = HTTPServer(("0.0.0.0", 18801), Handler)
    print("[bridge] Started on 18801"); server.serve_forever()

if __name__ == "__main__":
    main()
