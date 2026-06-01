#!/usr/bin/env python3
"""Fault-injection proxy between the bridge and the scenario's trigger server (:18802).

The bridge is started with CARLA_TRIGGER_URL=http://127.0.0.1:<proxy>/start_merge.
Mode file decides behaviour per request: 'fail' -> HTTP 503 (trigger failure), 'pass' -> forward to 18802.
Every request is logged with a timestamp. Validation tooling only; no production code involved.
"""
import json, sys, time, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT, MODE_FILE, LOG = int(sys.argv[1]), sys.argv[2], sys.argv[3]

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        mode = open(MODE_FILE).read().strip()
        code = 503
        if mode == "pass":
            try:
                req = urllib.request.Request("http://127.0.0.1:18802" + self.path, data=body, method="POST",
                                             headers={"Content-Type": "application/json"})
                code = urllib.request.urlopen(req, timeout=2).status
            except Exception:
                code = 502
        with open(LOG, "a") as f:
            f.write(json.dumps({"t": time.time(), "mode": mode, "path": self.path, "body": body.decode(), "code": code}) + "\n")
        self.send_response(code); self.end_headers()
    def log_message(self, *a): pass

HTTPServer(("127.0.0.1", PORT), H).serve_forever()
