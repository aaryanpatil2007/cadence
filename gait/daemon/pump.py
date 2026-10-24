"""EventPump: polls the capture ring buffer and fans raw events out to
in-RAM subscribers (scorer, enrollment, step-up). Nothing here touches disk.
"""
from __future__ import annotations

import threading
import time

from gait.capture.buffer import RingBuffer


class Subscriber:
    """Accumulates raw events in RAM; consumer drains or reads them."""

    def __init__(self, horizon_s: float | None = None):
        self.keys: list[dict] = []
        self.pointer: list[dict] = []
        self.horizon_s = horizon_s
        self.lock = threading.Lock()

    def add(self, keys: list[dict], pointer: list[dict]) -> None:
        with self.lock:
            self.keys.extend(keys)
            self.pointer.extend(pointer)
            if self.horizon_s is not None and (self.keys or self.pointer):
                newest = max([e["t"] for e in self.keys[-1:]] +
                             [e["t"] for e in self.pointer[-1:]])
                cutoff = newest - self.horizon_s
                self.keys = [e for e in self.keys if e["t"] >= cutoff]
                self.pointer = [e for e in self.pointer if e["t"] >= cutoff]

    def snapshot(self) -> tuple[list[dict], list[dict]]:
        with self.lock:
            return list(self.keys), list(self.pointer)

    def drain(self) -> tuple[list[dict], list[dict]]:
        with self.lock:
            k, p = self.keys, self.pointer
            self.keys, self.pointer = [], []
            return k, p


class EventPump:
    def __init__(self, buffer: RingBuffer, poll_s: float = 0.25):
        self.buffer = buffer
        self.poll_s = poll_s
        self._subs: list[Subscriber] = []
        self._last_t: float | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def subscribe(self, horizon_s: float | None = None) -> Subscriber:
        sub = Subscriber(horizon_s)
        with self._lock:
            self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    def _tick(self) -> None:
        keys, pointer = self.buffer.snapshot(since=self._last_t)
        if self._last_t is not None:
            keys = [e for e in keys if e["t"] > self._last_t]
            pointer = [e for e in pointer if e["t"] > self._last_t]
        ts = [e["t"] for e in keys] + [e["t"] for e in pointer]
        if ts:
            self._last_t = max(ts)
        if keys or pointer:
            with self._lock:
                subs = list(self._subs)
            for s in subs:
                s.add(keys, pointer)

    def start(self) -> None:
        def loop():
            while not self._stop.is_set():
                self._tick()
                time.sleep(self.poll_s)
        self._thread = threading.Thread(target=loop, daemon=True, name="gait-pump")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
