"""Synthetic bot sessions (negatives for training + calibration).

Generates raw-like event streams, then runs them through the real feature
extractors so bots and humans share one pipeline.
"""
from __future__ import annotations

import random
from pathlib import Path

from gait.features.keystroke import extract_key_windows
from gait.features.pointer import extract_pointer_windows
from gait.features.schema import WindowRecord

LETTERS = [0, 1, 2, 3, 5, 12, 13, 14, 15, 17, 16, 32, 34, 31, 35, 38, 40, 37, 45, 46]


def _key_events(n: int, hold_s: float, dd_s: float, jitter_s: float,
                rng: random.Random, t0: float = 0.0) -> list[dict]:
    evs, t = [], t0
    for _ in range(n):
        h = max(hold_s + rng.gauss(0, jitter_s), 0.005)
        code = rng.choice(LETTERS + [49])
        evs.append({"t": t, "type": "down", "keycode": code, "autorepeat": 0,
                    "shift_side": None, "cmd_side": None})
        evs.append({"t": t + h, "type": "up", "keycode": code, "autorepeat": 0,
                    "shift_side": None, "cmd_side": None})
        t += max(dd_s + rng.gauss(0, jitter_s), 0.01)
    return evs


def _pointer_events(duration_s: float, rng: random.Random,
                    jitter_px: float = 0.0, t0: float = 0.0) -> list[dict]:
    """Straight-line constant-speed moves between random targets + instant clicks."""
    evs, t = [], t0
    x, y = 500.0, 400.0
    while t < t0 + duration_s:
        tx, ty = rng.uniform(100, 1300), rng.uniform(100, 800)
        dist = ((tx - x) ** 2 + (ty - y) ** 2) ** 0.5
        speed = 1500.0  # px/s, perfectly constant
        steps = max(int(dist / speed * 100), 2)
        for i in range(steps):
            f = (i + 1) / steps
            evs.append({"t": t + f * dist / speed, "type": "move",
                        "x": x + (tx - x) * f + rng.gauss(0, jitter_px),
                        "y": y + (ty - y) * f + rng.gauss(0, jitter_px)})
        t += dist / speed
        evs.append({"t": t + 0.001, "type": "down", "x": tx, "y": ty,
                    "click_state": 1, "pressure": 0.0})
        evs.append({"t": t + 0.011, "type": "up", "x": tx, "y": ty})
        x, y = tx, ty
        t += 0.05
    return evs


def generate_bot_session(kind: str, seed: int, n_keys: int = 150,
                         duration_s: float = 60.0) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    if kind == "uniform":
        keys = _key_events(n_keys, hold_s=0.060, dd_s=0.090, jitter_s=0.0, rng=rng)
        ptr = _pointer_events(duration_s, rng, jitter_px=0.0)
    elif kind == "jitter":
        keys = _key_events(n_keys, hold_s=0.060, dd_s=0.090, jitter_s=0.003, rng=rng)
        ptr = _pointer_events(duration_s, rng, jitter_px=0.5)
    else:
        raise ValueError(kind)
    return keys, ptr


def replay_speed_session(key_events: list[dict], factor: float = 0.7) -> list[dict]:
    """Time-scale a genuine session (fast replay attack)."""
    if not key_events:
        return []
    t0 = min(e["t"] for e in key_events)
    return [{**e, "t": t0 + (e["t"] - t0) * factor} for e in key_events]


def generate_all(enroll_dir: Path, n_sessions: int = 10) -> dict[str, int]:
    """Write bot feature records under data/enroll/bot_synth_*/ (features only)."""
    counts = {}
    for kind in ("uniform", "jitter"):
        profile = f"bot_synth_{kind}"
        pdir = enroll_dir / profile
        pdir.mkdir(parents=True, exist_ok=True)
        total = 0
        for s in range(n_sessions):
            keys, ptr = generate_bot_session(kind, seed=1000 + s)
            sid = f"synth_{s:02d}"
            recs = (extract_key_windows(keys, profile, sid)
                    + extract_pointer_windows(ptr, profile, sid))
            with open(pdir / f"{sid}.jsonl", "w") as f:
                for r in recs:
                    f.write(r.to_json() + "\n")
            total += len(recs)
        counts[profile] = total
    return counts


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent.parent / "data" / "enroll"
    print(generate_all(root))
