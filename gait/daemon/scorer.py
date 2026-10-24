"""Rolling score loop: every hop, featurize the last window of raw events,
fuse modalities, update the EWMA, apply idle decay and the bot floor.
"""
from __future__ import annotations

import threading
import time

from gait.capture.buffer import RingBuffer
from gait.features.keystroke import pair_keystrokes, build_seq, window_stats
from gait.features.pointer import pointer_window_stats
from gait.features.schema import (
    WindowRecord, seq_item_to_row, MIN_KEYS, WINDOW_S, HOP_S,
)
from gait.model.fusion import RollingScore, fuse, BOT_FLOOR_P
from gait.model.runtime import ModelBundle
from .pump import EventPump


class Scorer:
    """Live scoring state machine. Also the base class the e2e test fakes."""

    def __init__(self, buffer: RingBuffer, pump: EventPump,
                 bundle: ModelBundle | None = None):
        self.buffer = buffer
        self.pump = pump
        self.bundle = bundle
        self.rolling = RollingScore()
        self.sub = pump.subscribe(horizon_s=WINDOW_S + 2.0)
        self.p_keys_last: float | None = None
        self.p_pointer_last: float | None = None
        self.bot_flag = False
        self.n_keys_last = 0
        self.n_pointer_last = 0
        self._stop = threading.Event()
        self._last_hop = 0.0
        # CGEventGetTimestamp and time.monotonic() should share the since-boot
        # base on macOS, but we don't trust that: estimate the offset from
        # event arrival so windowing works under any clock base.
        self._clock_offset: float | None = None

    def _event_now(self) -> float:
        """Current time expressed in the event-timestamp clock."""
        mono = time.monotonic()
        newest = self.buffer.last_input_t
        if newest is not None:
            off = mono - newest  # >= true offset (plus up to ~0.25s latency)
            if self._clock_offset is None or off < self._clock_offset:
                self._clock_offset = off
        return mono - (self._clock_offset or 0.0)

    # ---- public state ----

    @property
    def score(self) -> float | None:
        return self.rolling.S

    def last_input_age_s(self) -> float | None:
        t = self.buffer.last_input_t
        if t is None:
            return None
        return max(self._event_now() - t, 0.0)

    def status(self) -> dict:
        return {
            "score": self.score,
            "modalities": {"keys": self.p_keys_last, "pointer": self.p_pointer_last},
            "bot_flag": self.bot_flag,
            "last_input_age_s": self.last_input_age_s(),
            "ready": self.bundle is not None and self.bundle.ready(),
        }

    # ---- scoring ----

    def score_window(self, key_events: list[dict], pointer_events: list[dict],
                     now: float) -> float | None:
        """Featurize one window and return fused p (None if too little input)."""
        if self.bundle is None or not self.bundle.ready():
            return None
        p_k = None
        n_keys = 0
        bot = False
        strokes = pair_keystrokes(
            [e for e in key_events if now - WINDOW_S <= e["t"] <= now])
        if len(strokes) >= MIN_KEYS:
            n_keys = len(strokes)
            rec = WindowRecord(
                profile_id="live", session_id="live",
                t_start=now - WINDOW_S, t_end=now, modality="keys",
                feats=window_stats(strokes, WINDOW_S),
                seq=[seq_item_to_row(i) for i in build_seq(strokes)[-32:]],
            )
            p_k = self.bundle.p_keys(rec)
            # sparse windows have noisy stats: shrink toward neutral
            p_k = 0.5 + (p_k - 0.5) * min(1.0, n_keys / 20)
            bot = bot or self.bundle.is_bot_window(rec)

        p_m = None
        ptr = [e for e in pointer_events if now - WINDOW_S <= e["t"] <= now]
        n_ptr = len([e for e in ptr if e["type"] in ("move", "drag")])
        feats = pointer_window_stats(ptr, WINDOW_S) if ptr else None
        if feats is not None:
            rec = WindowRecord(
                profile_id="live", session_id="live",
                t_start=now - WINDOW_S, t_end=now, modality="pointer",
                feats=feats,
            )
            p_m = self.bundle.p_pointer(rec)
            bot = bot or self.bundle.is_bot_window(rec)

        self.p_keys_last = p_k
        self.p_pointer_last = p_m
        self.n_keys_last = n_keys
        self.n_pointer_last = n_ptr
        self.bot_flag = bot
        p, w = fuse(p_k, n_keys, p_m, n_ptr, bot)
        self.last_weight = w
        return p

    def tick(self) -> None:
        mono = time.monotonic()
        idle = self.last_input_age_s()
        if idle is not None:
            self.rolling.apply_idle(idle, mono)
        if mono - self._last_hop >= HOP_S:
            self._last_hop = mono
            keys, pointer = self.sub.snapshot()
            p = self.score_window(keys, pointer, self._event_now())
            if p is not None:
                # pointer alone sustains the score; only typing can raise it
                # (and only typing can initialize it)
                if self.n_keys_last == 0 and not self.bot_flag:
                    if self.rolling.S is None:
                        return
                    p = min(p, self.rolling.S)
                self.rolling.update(p, HOP_S, getattr(self, "last_weight", 1.0))

    def run(self) -> None:
        while not self._stop.is_set():
            self.tick()
            time.sleep(0.25)

    def start(self) -> threading.Thread:
        th = threading.Thread(target=self.run, daemon=True, name="gait-scorer")
        th.start()
        return th

    def stop(self) -> None:
        self._stop.set()


class FakeScorer(Scorer):
    """Injectable fixed-score scorer for e2e tests (no capture, no models)."""

    def __init__(self, fixed_score: float | None = 0.9):
        self.fixed = fixed_score
        self.p_keys_last = fixed_score
        self.p_pointer_last = fixed_score
        self.bot_flag = False
        self.n_keys_last = 20
        self.n_pointer_last = 200

    @property
    def score(self) -> float | None:
        return self.fixed

    def set(self, score: float | None) -> None:
        self.fixed = score
        self.p_keys_last = score
        self.p_pointer_last = score

    def last_input_age_s(self) -> float:
        return 0.5

    def status(self) -> dict:
        return {"score": self.fixed,
                "modalities": {"keys": self.fixed, "pointer": self.fixed},
                "bot_flag": False, "last_input_age_s": 0.5, "ready": True}

    def start(self):
        return None

    def stop(self) -> None:
        pass
