"""FakeCarlaScenario: a stand-in for scenario/examples/two_platoon_truck_scenario.py.

The bridge never calls the CARLA API directly. Its boundary with the CARLA side
is an HTTP contract, so this fake implements that contract instead of a Python
adapter:

    bridge   --POST {"request_id": ...}-->  <trigger_url>          (trigger)
    scenario --POST /transfers/<rid>/splitting|merging|carla_complete|failed-->  bridge

Difference from the real scenario (intentional, documented):
    The real scenario ignores the trigger body and polls GET /snapshot for a
    committed transfer. The fake reacts to the trigger directly and reads
    GET /transfers/<rid> once, so tests are deterministic and need no polling loop.

Modes select how the "CARLA side" behaves after a trigger:
    complete     splitting -> merging -> carla_complete
    silent       accept the trigger, never report progress (timeout case)
    fail         report /failed immediately
    partial      splitting -> merging -> /failed
    bad_response answer the trigger with HTTP 500 and report nothing
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

MODES = ("complete", "silent", "fail", "partial", "bad_response")


class FakeCarlaScenario:
    def __init__(self, bridge_url: str, mode: str = "complete", step_delay_s: float = 0.05):
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
        self.bridge_url = bridge_url.rstrip("/")
        self.mode = mode
        self.step_delay_s = step_delay_s
        # While `hold` is set, progress reports wait. Lets tests observe the
        # bridge state between "trigger accepted" and "physical progress".
        self.hold = threading.Event()
        self.triggers: list[dict] = []   # trigger bodies received, in order
        self.reports: list[tuple[str, str, int | None]] = []  # (request_id, step, bridge status code)
        self._stop = threading.Event()
        self._workers: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._server = HTTPServer(("127.0.0.1", 0), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    # ── lifecycle ────────────────────────────────────────────────────────────
    @property
    def trigger_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}/start_merge"

    def start(self) -> "FakeCarlaScenario":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self.hold.clear()
        self._server.shutdown()
        self._server.server_close()
        for w in self._workers:
            w.join(timeout=2.0)

    def release(self) -> None:
        """Let held progress reports continue."""
        self.hold.clear()

    def trigger_count(self) -> int:
        with self._lock:
            return len(self.triggers)

    # ── trigger receiver ─────────────────────────────────────────────────────
    def _make_handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw.decode() or "{}")
                except json.JSONDecodeError:
                    body = {"_unparsed": raw.decode(errors="replace")}
                with fake._lock:
                    fake.triggers.append(body)
                if fake.mode == "bad_response":
                    self.send_response(500)
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                rid = body.get("request_id")
                if rid and fake.mode != "silent":
                    w = threading.Thread(target=fake._report_progress, args=(rid,), daemon=True)
                    fake._workers.append(w)
                    w.start()

            def log_message(self, *args):
                pass

        return Handler

    # ── progress reporter (the "physical" side) ──────────────────────────────
    def _steps(self) -> list[str]:
        return {
            "complete": ["splitting", "merging", "carla_complete"],
            "fail": ["failed"],
            "partial": ["splitting", "merging", "failed"],
        }[self.mode]

    def _report_progress(self, rid: str) -> None:
        while self.hold.is_set() and not self._stop.is_set():
            time.sleep(0.01)
        for step in self._steps():
            if self._stop.is_set():
                return
            time.sleep(self.step_delay_s)
            body = {"reason": "fake carla failure"} if step == "failed" else {}
            code = self._post(f"/transfers/{rid}/{step}", body)
            with self._lock:
                self.reports.append((rid, step, code))

    def _post(self, path: str, body: dict) -> int | None:
        req = urllib.request.Request(
            f"{self.bridge_url}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=2) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception:
            return None
