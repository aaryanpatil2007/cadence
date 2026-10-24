"""Replay synthetic human/impostor/bot event streams through the LIVE scorer
path (ring buffer -> pump -> Scorer -> fusion/EWMA) at 20x speed.

Usage: .venv/bin/python scripts/replay_check.py
Honest robustness check after (re)training — works with whatever models are in
GAIT_DATA_DIR (defaults to data/).
"""
import math
import random
import time

from gait.capture.buffer import RingBuffer
from gait.daemon.pump import EventPump
from gait.daemon.scorer import Scorer
from gait.model.fakehuman import PROFILES, key_stream, pointer_stream
from gait.model.runtime import ModelBundle
from gait.model.synth import generate_bot_session


def replay(events, label, speedup=20.0, carry_S=None):
    buf = RingBuffer()
    pump = EventPump(buf, poll_s=0.02)
    pump.start()
    sc = Scorer(buf, pump, ModelBundle.load())
    if carry_S is not None:
        sc.rolling.S = carry_S
    BASE = 1e6  # alien clock base: exercises the clock-offset estimator
    t0 = time.monotonic()
    evs = sorted(events, key=lambda e: e["t"])
    i, scores, sim = 0, [], 0.0
    while sim < min(evs[-1]["t"], 60.0):
        sim = (time.monotonic() - t0) * speedup
        while i < len(evs) and evs[i]["t"] <= sim:
            e = dict(evs[i])
            e["t"] = BASE + e["t"]
            (buf.push_key if "keycode" in e else buf.push_pointer)(e)
            i += 1
        time.sleep(0.005)
        if sim >= (len(scores) + 1) * 2.5:
            time.sleep(0.05)
            k, p = sc.sub.snapshot()
            pr = sc.score_window(k, p, BASE + sim)
            if pr is not None:
                if sc.n_keys_last == 0 and not sc.bot_flag:
                    if sc.rolling.S is None:
                        scores.append(float("nan"))
                        continue
                    pr = min(pr, sc.rolling.S)
                scores.append(sc.rolling.update(pr, 2.5, sc.last_weight))
            else:
                scores.append(sc.rolling.S if sc.rolling.S is not None else float("nan"))
    pump.stop()
    valid = [s for s in scores if not math.isnan(s)]
    print(f"{label:>6}: final={valid[-1]:.3f}  max-tail8={max(valid[-8:]):.3f}  "
          f"peak={max(valid):.3f}")
    return valid


if __name__ == "__main__":
    u = PROFILES["user"]
    replay(key_stream(u, 220, random.Random(3))
           + pointer_stream(u, 55, random.Random(3)), "user")
    bk, bp = generate_bot_session("jitter", seed=9)
    replay(bk + bp, "bot", carry_S=0.9)
    for name, seed in (("impostor_1", 5), ("impostor_2", 6)):
        p = PROFILES[name]
        replay(key_stream(p, 220, random.Random(seed))
               + pointer_stream(p, 55, random.Random(seed)), name, carry_S=0.9)
