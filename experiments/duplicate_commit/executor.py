"""Isolated fault-injection model; not the production CARLA coordinator.

Restarting a request clears a latched emergency stop. The vulnerable mode is
kept explicitly for before/after reproduction, never enabled in production.
"""
import threading


class TransferExecutor:
    def __init__(self, deduplicate=True):
        self.deduplicate = deduplicate
        self.seen = set()
        self.starts = 0
        self.braking = True
        self.lock = threading.Lock()

    def commit(self, request_id):
        with self.lock:
            # Retries must preserve the active maneuver, including its safety stop.
            if self.deduplicate and request_id in self.seen:
                return False
            self.seen.add(request_id)
            self.starts += 1
            self.braking = False
            return True

    def emergency_stop(self):
        with self.lock:
            self.braking = True

    def control(self):
        with self.lock:
            return (0.0, 1.0) if self.braking else (1.0, 0.0)
