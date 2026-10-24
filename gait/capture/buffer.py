"""RAM-only ring buffer of raw events. Max 12 seconds retained; no file handles
exist anywhere in gait.capture — raw events are never persisted.
"""
from __future__ import annotations

import threading
from collections import deque

MAX_AGE_S = 12.0


class RingBuffer:
    def __init__(self, max_age_s: float = MAX_AGE_S):
        self.max_age_s = max_age_s
        self._key: deque[dict] = deque()
        self._pointer: deque[dict] = deque()
        self._lock = threading.Lock()
        self.last_input_t: float | None = None

    def push_key(self, ev: dict) -> None:
        with self._lock:
            self._key.append(ev)
            self.last_input_t = ev["t"]
            self._evict(ev["t"])

    def push_pointer(self, ev: dict) -> None:
        with self._lock:
            self._pointer.append(ev)
            self.last_input_t = ev["t"]
            self._evict(ev["t"])

    def _evict(self, now: float) -> None:
        cutoff = now - self.max_age_s
        while self._key and self._key[0]["t"] < cutoff:
            self._key.popleft()
        while self._pointer and self._pointer[0]["t"] < cutoff:
            self._pointer.popleft()

    def snapshot(self, since: float | None = None) -> tuple[list[dict], list[dict]]:
        """Copy of current events (optionally only those with t >= since)."""
        with self._lock:
            k = [e for e in self._key if since is None or e["t"] >= since]
            p = [e for e in self._pointer if since is None or e["t"] >= since]
            return k, p

    def span_s(self) -> float:
        with self._lock:
            ts = [e["t"] for e in list(self._key) + list(self._pointer)]
        return (max(ts) - min(ts)) if len(ts) > 1 else 0.0
