"""Shared fixtures: run the real bridge in-process, wired to a FakeCarlaScenario.

No production code is modified. The bridge module is imported as-is and its
existing `Handler` is served on an ephemeral port. Test isolation uses the
bridge's own POST /reload endpoint.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import sys
import threading
import time
from http.server import HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bridge"))
sys.path.insert(0, str(ROOT / "tests"))

# Must be set before import: the bridge reads these at module load time.
os.environ["PLATOON_DESTINATIONS_PATH"] = str(ROOT / "tests" / "fixtures" / "platoons.json")
os.environ["MOCK_CARLA"] = "false"

import platoon_bridge_server as bridge  # noqa: E402
from fakes.fake_carla import FakeCarlaScenario  # noqa: E402


class BridgeClient:
    """Minimal HTTP client. Returns (status, json_body).

    A dropped connection (no HTTP response at all) raises, so tests see it as
    a failure instead of hanging.
    """

    def __init__(self, host: str, port: int, timeout: float = 3.0):
        self.host, self.port, self.timeout = host, port, timeout

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def request(self, method: str, path: str, body=None, raw: bytes | None = None):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        headers = {"Content-Type": "application/json"} if data is not None else {}
        try:
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            text = resp.read().decode()
            try:
                payload = json.loads(text) if text else None
            except json.JSONDecodeError:
                payload = {"_raw": text}
            return resp.status, payload
        finally:
            conn.close()

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=None):
        return self.request("POST", path, body if body is not None else {})

    # convenience
    def snapshot(self):
        return self.get("/snapshot")[1]

    def transfer(self, rid):
        return self.get(f"/transfers/{rid}")[1]

    def members(self, platoon_id):
        return [m["vehicle_id"] for m in self.get(f"/platoons/{platoon_id}")[1]["members"]]

    def wait_for_status(self, rid, wanted, timeout=5.0):
        wanted = {wanted} if isinstance(wanted, str) else set(wanted)
        deadline = time.monotonic() + timeout
        status = None
        while time.monotonic() < deadline:
            status = self.transfer(rid).get("status")
            if status in wanted:
                return status
            time.sleep(0.02)
        raise AssertionError(f"transfer {rid} status={status!r}, expected one of {sorted(wanted)} within {timeout}s")


@pytest.fixture(scope="session")
def bridge_server():
    server = HTTPServer(("127.0.0.1", 0), bridge.Handler)
    server.RequestHandlerClass.log_message = lambda *a: None
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def client(bridge_server, monkeypatch):
    c = BridgeClient("127.0.0.1", bridge_server.server_port)
    monkeypatch.setattr(bridge, "MOCK_MODE", False)
    status, _ = c.post("/reload")
    assert status == 200
    return c


@pytest.fixture
def fake_carla(client, monkeypatch):
    """FakeCarlaScenario in 'complete' mode, already wired as the bridge's trigger target."""
    fake = FakeCarlaScenario(client.base_url, mode="complete").start()
    monkeypatch.setattr(bridge, "CARLA_TRIGGER_URL", fake.trigger_url)
    yield fake
    fake.stop()


@pytest.fixture
def unreachable_trigger(monkeypatch):
    """Point the bridge at a port with nothing listening (CARLA side down)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    url = f"http://127.0.0.1:{port}/start_merge"
    monkeypatch.setattr(bridge, "CARLA_TRIGGER_URL", url)
    return url
