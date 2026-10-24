"""Human-like synthetic profiles for pipeline testing (NOT demo data).

Lets the full train/calibrate/eval pipeline run before real enrollment.
Each profile has distinct typing + pointer dynamics with human-scale noise.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from gait.features.keystroke import extract_key_windows
from gait.features.pointer import extract_pointer_windows

LETTERS_L = [0, 1, 2, 3, 5, 12, 13, 14, 15, 17]
LETTERS_R = [16, 32, 34, 31, 35, 38, 40, 37, 45, 46]

PROFILES = {
    "user":       dict(hold=0.095, hold_sd=0.025, dd=0.18, dd_sd=0.08,
                       speed=850, curve=0.35, dwell=0.09, pause_p=0.06),
    "impostor_1": dict(hold=0.068, hold_sd=0.016, dd=0.13, dd_sd=0.05,
                       speed=1250, curve=0.18, dwell=0.06, pause_p=0.03),
    "impostor_2": dict(hold=0.125, hold_sd=0.032, dd=0.24, dd_sd=0.11,
                       speed=600, curve=0.55, dwell=0.13, pause_p=0.10),
}


def key_stream(p: dict, n: int, rng: random.Random, t0: float = 0.0) -> list[dict]:
    evs, t = [], t0
    for i in range(n):
        if rng.random() < p["pause_p"]:
            t += rng.uniform(0.8, 2.5)  # thinking pause
        hold = max(rng.gauss(p["hold"], p["hold_sd"]), 0.02)
        code = rng.choice(LETTERS_L + LETTERS_R + [49, 49])
        shift = rng.random() < 0.04
        evs.append({"t": t, "type": "down", "keycode": code, "autorepeat": 0,
                    "shift_side": "L" if shift else None, "cmd_side": None})
        evs.append({"t": t + hold, "type": "up", "keycode": code, "autorepeat": 0,
                    "shift_side": "L" if shift else None, "cmd_side": None})
        # lognormal-ish inter-key interval
        dd = max(rng.gauss(p["dd"], p["dd_sd"]), 0.04)
        t += dd
    return evs


def pointer_stream(p: dict, duration_s: float, rng: random.Random,
                   t0: float = 0.0) -> list[dict]:
    """Curved, speed-varying movements with submovements and noisy clicks."""
    evs, t = [], t0
    x, y = 600.0, 400.0
    while t < t0 + duration_s:
        tx, ty = rng.uniform(100, 1300), rng.uniform(100, 800)
        dist = math.hypot(tx - x, ty - y)
        dur = max(dist / p["speed"] * rng.uniform(0.8, 1.3), 0.15)
        steps = max(int(dur * 100), 8)
        # control point for a curved (quadratic bezier) path
        mx = (x + tx) / 2 + rng.gauss(0, p["curve"] * dist * 0.3)
        my = (y + ty) / 2 + rng.gauss(0, p["curve"] * dist * 0.3)
        for i in range(steps):
            f = (i + 1) / steps
            ease = 0.5 - 0.5 * math.cos(math.pi * f)  # bell speed profile
            u = ease
            px = (1 - u) ** 2 * x + 2 * (1 - u) * u * mx + u ** 2 * tx
            py = (1 - u) ** 2 * y + 2 * (1 - u) * u * my + u ** 2 * ty
            evs.append({"t": t + f * dur, "type": "move",
                        "x": px + rng.gauss(0, 1.2), "y": py + rng.gauss(0, 1.2)})
        t += dur
        # small correction submovement near target
        for i in range(5):
            evs.append({"t": t + i * 0.012, "type": "move",
                        "x": tx + rng.gauss(0, 2.5), "y": ty + rng.gauss(0, 2.5)})
        t += 0.07
        dwell = max(rng.gauss(p["dwell"], 0.02), 0.03)
        evs.append({"t": t, "type": "down", "x": tx, "y": ty,
                    "click_state": 1, "pressure": rng.uniform(0.2, 0.7)})
        evs.append({"t": t + dwell, "type": "up", "x": tx, "y": ty})
        t += dwell + rng.uniform(0.1, 0.7)
        x, y = tx, ty
    return evs


def generate_profiles(enroll_root: Path, n_keys: int = 600,
                      pointer_s: float = 240.0, seed: int = 7) -> None:
    for name, p in PROFILES.items():
        rng = random.Random(seed + hash(name) % 1000)
        pdir = enroll_root / name
        pdir.mkdir(parents=True, exist_ok=True)
        for sess in range(2):
            sid = f"fake_{sess:02d}"
            keys = key_stream(p, n_keys // 2, rng)
            ptr = pointer_stream(p, pointer_s / 2, rng)
            recs = (extract_key_windows(keys, name, sid)
                    + extract_pointer_windows(ptr, name, sid))
            with open(pdir / f"{sid}.jsonl", "w") as f:
                for r in recs:
                    f.write(r.to_json() + "\n")


if __name__ == "__main__":
    from gait.paths import enroll_dir
    generate_profiles(enroll_dir())
    print("fake human profiles written (replace with real enrollment!)")
