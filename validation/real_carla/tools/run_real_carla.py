#!/usr/bin/env python3
"""Real-CARLA re-validation driver (validation tooling; production code is run unchanged).

For every run:
  1. start the existing scenario (scenario/examples/two_platoon_truck_scenario.py) with the
     CARLA 0.9.13 Python 3.7 client -> it reloads the bridge and Town06 itself
  2. drive the bridge through its normal REST contract
       normal     : the existing tools/openclaw_negotiation_harness.py (request -> accept -> commit -> wait)
       duplicate  : request -> accept -> commit x3 (same request_id)
       recovery   : trigger path broken by fault_proxy (HTTP 503) -> trigger_failed ->
                    new request accepted -> proxy restored -> accept/commit -> completion
  3. record every status transition seen on GET /snapshot (polled every 0.2 s, wall clock)
  4. after the final status: read the PHYSICAL truck positions/lanes from CARLA (phys_snapshot.py)
     and compare with the bridge's LOGICAL membership
  5. count CARLA trigger sends (bridge log) and physical split starts / joins (scenario log)
Rows are appended to raw_results.csv. Nothing here is synthesized: every value comes from a log,
the bridge API or the CARLA server.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CARLA = Path.home() / "carla-0.9.13"
EGG = CARLA / "PythonAPI/carla/dist/carla-0.9.13-py3.7-linux-x86_64.egg"
SCEN_ENV = {**os.environ, "PYTHONPATH": f"{EGG}:{CARLA / 'PythonAPI/carla'}:{ROOT / 'scenario/src'}"}
BRIDGE = "http://127.0.0.1:18801"
VEH, FROM, TO = "platoon_a_truck1", "platoon_a", "platoon_b"


def http(method, path, body=None, timeout=5):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BRIDGE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "null")


class Poller(threading.Thread):
    """Records (wall_time, request_id, status) whenever a transfer's status changes."""

    def __init__(self):
        super().__init__(daemon=True)
        self.events, self.last, self.stop_flag = [], {}, threading.Event()

    def run(self):
        while not self.stop_flag.is_set():
            try:
                _, snap = http("GET", "/snapshot", timeout=2)
                now = time.time()
                for rid, t in (snap or {}).get("transfers", {}).items():
                    if self.last.get(rid) != t["status"]:
                        self.last[rid] = t["status"]
                        self.events.append({"t": now, "rid": rid, "status": t["status"], "reason": t.get("reason")})
            except Exception:
                pass
            time.sleep(0.2)

    def first(self, rid, status):
        return next((e["t"] for e in self.events if e["rid"] == rid and e["status"] == status), None)

    def wait_final(self, rid, timeout, finals=("carla_complete", "merge_failed", "trigger_failed", "rejected")):
        end = time.time() + timeout
        while time.time() < end:
            if self.last.get(rid) in finals:
                return self.last[rid]
            time.sleep(0.2)
        return self.last.get(rid)


def iso_to_epoch(s):
    return dt.datetime.fromisoformat(s).timestamp()


def port_open(port):
    import socket
    with socket.socket() as so:
        so.settimeout(1)
        return so.connect_ex(("127.0.0.1", port)) == 0


def start_carla(log_path):
    """Fresh CARLA 0.9.13 server per run (repeated load_world on one server segfaulted during tool bring-up)."""
    f = open(log_path, "w")
    p = subprocess.Popen([str(CARLA / "CarlaUE4.sh"), "-RenderOffScreen", "-quality-level=Low", "-carla-rpc-port=2000"],
                         cwd=str(CARLA), stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
    end = time.time() + 120
    while time.time() < end:
        if p.poll() is not None:
            raise RuntimeError(f"CARLA server exited (code {p.returncode})")
        if port_open(2000):
            chk = subprocess.run(["python3.7", "-c", "import carla;c=carla.Client('127.0.0.1',2000);c.set_timeout(20);print(c.get_server_version())"],
                                 env=SCEN_ENV, capture_output=True, text=True, timeout=60)
            if chk.returncode == 0:
                return p, f
        time.sleep(2)
    raise RuntimeError("CARLA server did not become ready within 120 s")


def stop_carla(p, f):
    if p.poll() is None:
        os.killpg(p.pid, signal.SIGTERM)
        try:
            p.wait(30)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL); p.wait()
    f.close()
    end = time.time() + 30
    while port_open(2000) and time.time() < end:
        time.sleep(1)


def start_scenario(log_path):
    f = open(log_path, "w")
    p = subprocess.Popen(["python3.7", "-u", str(ROOT / "scenario/examples/two_platoon_truck_scenario.py")],
                         cwd=str(ROOT), env=SCEN_ENV, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         start_new_session=True)
    end = time.time() + 180
    while time.time() < end:
        if p.poll() is not None:
            raise RuntimeError(f"scenario exited early (code {p.returncode}), see {log_path}")
        if "t=" in Path(log_path).read_text(errors="replace"):
            return p, f
        time.sleep(1)
    raise RuntimeError("scenario did not start within 180 s")


def stop_scenario(p, f):
    if p.poll() is None:
        os.killpg(p.pid, signal.SIGINT)
        try:
            p.wait(20)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL); p.wait()
    f.close()


def phys_snapshot():
    out = subprocess.run(["python3.7", str(HERE / "phys_snapshot.py")], env=SCEN_ENV, capture_output=True, text=True, timeout=60)
    return json.loads(out.stdout.strip().splitlines()[-1])


def physical_check(phys, expect_transfer=True):
    v = phys["vehicles"]
    b_lane = {v[n]["lane_id"] for n in ("platoon_b_truck0", "platoon_b_truck1", "platoon_b_truck2")}
    a_lane = {v[n]["lane_id"] for n in ("platoon_a_truck0", "platoon_a_truck2")}
    t = v[VEH]
    if expect_transfer:
        behind = v["platoon_b_truck2"]["x"] - t["x"]
        ok = len(b_lane) == 1 and t["lane_id"] in b_lane and t["lane_id"] not in a_lane and 0 < behind < 40
        return ok, f"B lanes={sorted(b_lane)} A lanes={sorted(a_lane)} truck1 lane={t['lane_id']} gap_to_b2={behind:.1f}m"
    ok = t["lane_id"] in a_lane and t["lane_id"] not in b_lane
    return ok, f"B lanes={sorted(b_lane)} A lanes={sorted(a_lane)} truck1 lane={t['lane_id']} (expected to stay in A)"


def count(path, needle):
    return Path(path).read_text(errors="replace").count(needle)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["normal", "duplicate", "recovery"], required=True)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--warmup", type=float, default=5.0)
    ap.add_argument("--run-timeout", type=float, default=600.0)
    ap.add_argument("--label", default="")
    ap.add_argument("--bridge-script", default=str(ROOT / "bridge/platoon_bridge_server.py"),
                    help="bridge implementation to run (e.g. the research-baseline version for comparison)")
    args = ap.parse_args()

    ev = HERE.parent / "evidence"; ev.mkdir(exist_ok=True)
    csv_path = HERE.parent / "raw_results.csv"
    stamp = time.strftime("%Y%m%d_%H%M%S")
    mode_file = ev / f"{args.mode}_{stamp}_proxy_mode.txt"
    proxy_log = ev / f"{args.mode}_{stamp}_proxy.jsonl"
    bridge_log = ev / f"{args.mode}_{stamp}_bridge.log"
    benv = dict(os.environ)
    procs = []
    if args.mode == "recovery":
        mode_file.write_text("fail")
        procs.append(subprocess.Popen([sys.executable, str(HERE / "fault_proxy.py"), "18899", str(mode_file), str(proxy_log)]))
        benv["CARLA_TRIGGER_URL"] = "http://127.0.0.1:18899/start_merge"
    bf = open(bridge_log, "w")
    benv.setdefault("PLATOON_DESTINATIONS_PATH", str(ROOT / "platoon_destinations.json"))
    procs.append(subprocess.Popen([sys.executable, "-u", args.bridge_script], cwd=str(ROOT),
                                  env=benv, stdout=bf, stderr=subprocess.STDOUT))
    time.sleep(1.5)
    assert http("GET", "/health")[0] == 200, "bridge not up"

    new_file = not csv_path.exists()
    with open(csv_path, "a", newline="") as fcsv:
        w = csv.writer(fcsv)
        if new_file:
            w.writerow(["timestamp", "mode", "run", "request_id", "final_status", "success",
                        "t_request_to_commit_s", "t_commit_to_physical_start_s", "t_commit_to_carla_complete_s",
                        "t_request_to_carla_complete_s", "commit_requests", "carla_trigger_sent", "trigger_failed_logged",
                        "physical_split_starts", "physical_joins", "logical_A", "logical_B",
                        "physical_check", "physical_detail", "recovery_new_request_status", "notes", "scenario_log"])
        for i in range(1, args.runs + 1):
            if args.mode == "recovery":
                mode_file.write_text("fail")
            slog = ev / f"{args.mode}_{stamp}_run{i}_scenario.log"
            start_bridge_lines = len(bridge_log.read_text(errors="replace").splitlines())
            poller = Poller(); p = f = None
            try:
                cp, cf = start_carla(ev / f"{args.mode}_{stamp}_run{i}_carla_server.log")
                p, f = start_scenario(slog)
            except Exception as e:
                w.writerow([time.strftime("%Y-%m-%dT%H:%M:%S"), args.mode + (f"[{args.label}]" if args.label else ""), i, "", "env_error", False] + [""] * 14 + [f"environment: {e}", slog.name])
                fcsv.flush(); print(f"[{args.mode} run {i}] ENV ERROR {e}", flush=True)
                if p: stop_scenario(p, f)
                try: stop_carla(cp, cf)
                except Exception: pass
                continue
            poller.start()
            notes, recovery_status, commit_requests = [], "", 1
            try:
                time.sleep(args.warmup)
                if args.mode == "normal":
                    h = subprocess.run([sys.executable, str(ROOT / "tools/openclaw_negotiation_harness.py"), "--vehicle-id", VEH,
                                        "--wait-complete", "--timeout", str(args.run_timeout), "--poll-interval", "1"],
                                       cwd=str(ROOT), capture_output=True, text=True, timeout=args.run_timeout + 60)
                    (ev / f"{args.mode}_{stamp}_run{i}_harness.log").write_text(h.stdout + h.stderr)
                    rid = next((ln.split(":", 1)[1].strip() for ln in h.stdout.splitlines() if ln.startswith("request_id:")), None)
                    notes.append(f"harness_exit={h.returncode}")
                else:
                    s, t = http("POST", "/transfers", {"vehicle_id": VEH, "from_platoon_id": FROM, "to_platoon_id": TO})
                    rid = t["request_id"]; http("POST", f"/transfers/{rid}/accept")
                    if args.mode == "duplicate":
                        commit_requests = 3
                        codes = [http("POST", f"/transfers/{rid}/commit")[0] for _ in range(3) if not time.sleep(0.3)]
                        notes.append(f"commit_http={codes}")
                    else:  # recovery
                        c1 = http("POST", f"/transfers/{rid}/commit")[0]
                        st = poller.wait_final(rid, 15, finals=("trigger_failed",))
                        notes.append(f"commit_http={c1} after_failure_status={st}")
                        s2, t2 = http("POST", "/transfers", {"vehicle_id": VEH, "from_platoon_id": FROM, "to_platoon_id": TO})
                        recovery_status = f"{s2}"
                        notes.append(f"failed_rid={rid}")
                        mode_file.write_text("pass")
                        if s2 == 200:
                            rid = t2["request_id"]; http("POST", f"/transfers/{rid}/accept")
                            commit_requests = 1
                            notes.append(f"recovery_commit_http={http('POST', f'/transfers/{rid}/commit')[0]}")
                        else:  # new request refused: follow what happens to the original transfer
                            notes.append(f"new_request_refused={s2}; following original transfer")
                final = poller.wait_final(rid, args.run_timeout) if rid else None
                time.sleep(8)  # let the joined vehicle settle behind the receiver tail
                phys = phys_snapshot()
                (ev / f"{args.mode}_{stamp}_run{i}_physical.json").write_text(json.dumps(phys, indent=2))
                _, snap = http("GET", "/snapshot")
                (ev / f"{args.mode}_{stamp}_run{i}_bridge_snapshot.json").write_text(json.dumps(snap, indent=2))
                la = [m["vehicle_id"] for m in snap["platoons"]["platoon_a"]["members"]]
                lb = [m["vehicle_id"] for m in snap["platoons"]["platoon_b"]["members"]]
                pok, pdetail = physical_check(phys, expect_transfer=(final == "carla_complete"))
                tr = snap["transfers"].get(rid, {})
                t_req = iso_to_epoch(tr["created_at"]) if tr.get("created_at") else None
                t_com, t_done = poller.first(rid, "committed"), poller.first(rid, "carla_complete")
                # the scenario posts /splitting and /merging in the same tick; take whichever was observed first
                starts = [x for x in (poller.first(rid, "splitting"), poller.first(rid, "merging")) if x]
                t_spl = min(starts) if starts else None
                d = lambda a, b: round(b - a, 2) if a and b else ""
                blines = bridge_log.read_text(errors="replace").splitlines()[start_bridge_lines:]
                trig_sent = sum(1 for ln in blines if "CARLA trigger sent" in ln and rid in ln)
                trig_fail = sum(1 for ln in blines if "CARLA trigger failed" in ln)
                logical_ok = (VEH in lb and VEH not in la) if final == "carla_complete" else (VEH in la and VEH not in lb)
                success = final == "carla_complete" and pok and logical_ok
                w.writerow([time.strftime("%Y-%m-%dT%H:%M:%S"), args.mode + (f"[{args.label}]" if args.label else ""), i, rid, final, success,
                            d(t_req, t_com), d(t_com, t_spl), d(t_com, t_done), d(t_req, t_done),
                            commit_requests, trig_sent, trig_fail,
                            count(slog, "-> LC started"), count(slog, ">>> JOIN COMPLETE"),
                            " ".join(la), " ".join(lb), pok, pdetail, recovery_status, "; ".join(notes), slog.name])
                fcsv.flush()
                print(f"[{args.mode} run {i}] final={final} success={success} {pdetail} {'; '.join(notes)}", flush=True)
            except Exception as e:
                w.writerow([time.strftime("%Y-%m-%dT%H:%M:%S"), args.mode + (f"[{args.label}]" if args.label else ""), i, "", "error", False] + [""] * 14 + [f"error: {e}", slog.name])
                fcsv.flush()
                print(f"[{args.mode} run {i}] ERROR {e}", flush=True)
            finally:
                poller.stop_flag.set()
                (ev / f"{args.mode}_{stamp}_run{i}_events.json").write_text(json.dumps(poller.events, indent=2))
                stop_scenario(p, f)
                stop_carla(cp, cf)
                time.sleep(3)
    for pr in procs:
        pr.terminate()
    bf.close()


if __name__ == "__main__":
    main()
