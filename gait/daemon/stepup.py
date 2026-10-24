"""Step-up challenge: type one sentence, re-score just that typing."""
from __future__ import annotations

import random
import time

from gait.features.keystroke import extract_key_windows
from gait.model.fusion import BOT_FLOOR_P
from .pump import EventPump, Subscriber
from .sentences import SENTENCES


class StepUpManager:
    def __init__(self, pump: EventPump, get_bundle):
        self.pump = pump
        self.get_bundle = get_bundle  # callable -> ModelBundle | None
        self.sub: Subscriber | None = None
        self.t0: float | None = None
        self.sentence: str | None = None

    def start(self) -> dict:
        if self.sub:
            self.pump.unsubscribe(self.sub)
        self.sub = self.pump.subscribe(horizon_s=None)
        self.t0 = time.monotonic()
        self.sentence = random.choice(SENTENCES)
        return {"challenge": self.sentence}

    def finish(self) -> dict:
        if not self.sub:
            return {"error": "no step-up in progress"}
        keys, _ = self.sub.drain()
        self.pump.unsubscribe(self.sub)
        self.sub = None
        bundle = self.get_bundle()
        if bundle is None or not bundle.ready():
            return {"error": "models not trained"}
        recs = extract_key_windows(keys, "stepup", "stepup")
        if not recs:
            return {"score": 0.0, "windows": 0,
                    "reason": "not enough keystrokes captured"}
        ps = []
        for r in recs:
            p = BOT_FLOOR_P if bundle.is_bot_window(r) else bundle.p_keys(r)
            ps.append(p)
        score = float(sum(ps) / len(ps))
        return {"score": round(score, 4), "windows": len(recs)}
