"""Pointer feature extraction: raw move/click/scroll events -> per-window stats.

Raw events: {t, type: 'move'|'down'|'up'|'scroll', x, y, pressure?,
             click_state?, delta_x?, delta_y?, momentum?, continuous?}
"""
from __future__ import annotations

import numpy as np

from .schema import (
    WindowRecord, POINTER_STAT_NAMES,
    MIN_POINTER_SAMPLES, MIN_CLICKS, MIN_SCROLLS,
)

RESAMPLE_HZ = 100.0
MOVE_GAP_S = 0.150


def _resample(moves: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Linear-interp trajectory to 100 Hz. Returns (t, x, y)."""
    t = np.array([m["t"] for m in moves])
    x = np.array([m["x"] for m in moves])
    y = np.array([m["y"] for m in moves])
    order = np.argsort(t)
    t, x, y = t[order], x[order], y[order]
    keep = np.concatenate([[True], np.diff(t) > 1e-6])
    t, x, y = t[keep], x[keep], y[keep]
    if len(t) < 2:
        return t, x, y
    tt = np.arange(t[0], t[-1], 1.0 / RESAMPLE_HZ)
    return tt, np.interp(tt, t, x), np.interp(tt, t, y)


def _split_movements(t: np.ndarray, x: np.ndarray, y: np.ndarray,
                     click_times: list[float]) -> list[slice]:
    """Split resampled trajectory into movements on temporal gaps or clicks."""
    if len(t) < 3:
        return []
    speed = np.hypot(np.diff(x), np.diff(y)) / np.maximum(np.diff(t), 1e-6)
    moving = speed > 3.0  # px/s
    bounds = [0]
    for ct in sorted(click_times):
        idx = int(np.searchsorted(t, ct))
        if 0 < idx < len(t):
            bounds.append(idx)
    # gaps where pointer is still for > MOVE_GAP_S
    still_run = 0
    for i, mv in enumerate(moving):
        if not mv:
            still_run += 1
            if still_run * (1.0 / RESAMPLE_HZ) > MOVE_GAP_S:
                bounds.append(i)
                still_run = 0
        else:
            still_run = 0
    bounds = sorted(set(bounds + [len(t)]))
    out = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b - a >= 10:  # >= 100 ms of trajectory
            seg_path = np.hypot(np.diff(x[a:b]), np.diff(y[a:b])).sum()
            if seg_path > 20:  # actual movement, not jitter
                out.append(slice(a, b))
    return out


def _movement_feats(t, x, y, seg: slice, clicks: list[dict]) -> dict:
    ts, xs, ys = t[seg], x[seg], y[seg]
    dt = np.maximum(np.diff(ts), 1e-6)
    vx, vy = np.diff(xs) / dt, np.diff(ys) / dt
    speed = np.hypot(vx, vy)
    accel = np.diff(speed) / dt[1:] if len(speed) > 1 else np.array([0.0])
    jerk = np.diff(accel) / dt[2:] if len(accel) > 1 else np.array([0.0])
    heading = np.arctan2(vy, vx)
    dh = np.abs(np.diff(np.unwrap(heading))) if len(heading) > 1 else np.array([0.0])
    path = np.hypot(np.diff(xs), np.diff(ys)).sum()
    chord = float(np.hypot(xs[-1] - xs[0], ys[-1] - ys[0]))
    straightness = chord / path if path > 1e-6 else 1.0
    # submovements: local minima in smoothed speed profile
    if len(speed) > 4:
        k = np.ones(5) / 5
        sm = np.convolve(speed, k, mode="same")
        minima = np.sum((sm[1:-1] < sm[:-2]) & (sm[1:-1] < sm[2:]) & (sm[1:-1] < 0.5 * sm.max()))
        submoves = int(minima) + 1
    else:
        submoves = 1
    # overshoot before a click ending this movement: distance traveled after first
    # passing within 10 px of the eventual click point
    overshoot = 0.0
    for c in clicks:
        if ts[0] <= c["t"] <= ts[-1] + 0.2:
            d_to_click = np.hypot(xs - c["x"], ys - c["y"])
            near = np.nonzero(d_to_click < 10.0)[0]
            if len(near) and near[0] < len(xs) - 1:
                i0 = near[0]
                extra = np.hypot(np.diff(xs[i0:]), np.diff(ys[i0:])).sum()
                overshoot = float(extra / max(path, 1e-6))
            break
    return dict(
        speed_mean=float(speed.mean()), speed_std=float(speed.std()),
        speed_max=float(speed.max()),
        accel_mean=float(np.abs(accel).mean()), accel_std=float(np.abs(accel).std()),
        jerk_mean=float(np.abs(jerk).mean()),
        curvature_mean=float(dh.mean()), curvature_std=float(dh.std()),
        straightness=straightness, duration=float(ts[-1] - ts[0]),
        submoves=submoves, overshoot=overshoot,
    )


def pointer_window_stats(events: list[dict], window_s: float = 5.0) -> list[float] | None:
    moves = [e for e in events if e["type"] in ("move", "drag")]
    downs = [e for e in events if e["type"] == "down"]
    ups = [e for e in events if e["type"] == "up"]
    scrolls = [e for e in events if e["type"] == "scroll"]

    if len(moves) < MIN_POINTER_SAMPLES and len(downs) < MIN_CLICKS and len(scrolls) < MIN_SCROLLS:
        return None

    mstats = []
    t = np.array([])
    x = y = t
    if len(moves) >= 5:
        t, x, y = _resample(moves)
        segs = _split_movements(t, x, y, [d["t"] for d in downs])
        mstats = [_movement_feats(t, x, y, s, downs) for s in segs]

    def agg(key, default=0.0):
        vals = [m[key] for m in mstats]
        return float(np.mean(vals)) if vals else default

    # clicks
    dwell = []
    for d in downs:
        after = [u for u in ups if u["t"] >= d["t"]]
        if after:
            dwell.append(after[0]["t"] - d["t"])
    dbl = [d["t"] for d in downs if d.get("click_state", 1) >= 2]
    dbl_interval = 0.0
    if dbl:
        prev = [d["t"] for d in downs if d["t"] < dbl[0]]
        if prev:
            dbl_interval = dbl[0] - prev[-1]
    pressures = [d.get("pressure", 0.0) or 0.0 for d in downs + ups]

    # scroll
    sc_rate = len(scrolls) / window_s
    sc_delta = float(np.mean([abs(s.get("delta_y", 0)) + abs(s.get("delta_x", 0))
                              for s in scrolls])) if scrolls else 0.0
    sc_momentum = float(np.mean([1.0 if s.get("momentum") else 0.0
                                 for s in scrolls])) if scrolls else 0.0
    signs = [np.sign(s.get("delta_y", 0)) for s in scrolls if s.get("delta_y", 0) != 0]
    reversals = sum(1 for a, b in zip(signs[:-1], signs[1:]) if a != b)
    sc_reversal = reversals / max(len(signs) - 1, 1) if len(signs) > 1 else 0.0
    sc_continuous = float(np.mean([1.0 if s.get("continuous") else 0.0
                                   for s in scrolls])) if scrolls else 0.0

    # idle jitter: position std during near-still stretches
    idle_jitter = 0.0
    if len(t) > 10:
        speed = np.hypot(np.diff(x), np.diff(y)) / np.maximum(np.diff(t), 1e-6)
        still = speed < 5.0
        if still.sum() > 10:
            idle_jitter = float(np.std(x[:-1][still]) + np.std(y[:-1][still])) / 2

    straightness_vals = [m["straightness"] for m in mstats]
    feats = [
        agg("speed_mean"), agg("speed_std"), agg("speed_max"),
        agg("accel_mean"), agg("accel_std"), agg("jerk_mean"),
        agg("curvature_mean"), agg("curvature_std"),
        float(np.mean(straightness_vals)) if straightness_vals else 0.0,
        float(np.std(straightness_vals)) if straightness_vals else 0.0,
        agg("duration"), agg("submoves"), agg("overshoot"),
        float(np.mean(dwell)) if dwell else 0.0,
        dbl_interval,
        float(np.mean(pressures)) if pressures else 0.0,
        float(np.max(pressures)) if pressures else 0.0,
        sc_rate, sc_delta, sc_momentum, sc_reversal, sc_continuous,
        idle_jitter,
        float(len(mstats)), float(len(downs)),
    ]
    assert len(feats) == len(POINTER_STAT_NAMES)
    return feats


def extract_pointer_windows(
    events: list[dict], profile_id: str, session_id: str,
    window_s: float = 5.0, hop_s: float = 2.5,
) -> list[WindowRecord]:
    if not events:
        return []
    events = sorted(events, key=lambda e: e["t"])
    t0, t_last = events[0]["t"], events[-1]["t"]
    records = []
    t = t0
    while t <= t_last + 1e-9:
        win = [e for e in events if t <= e["t"] < t + window_s]
        feats = pointer_window_stats(win, window_s)
        if feats is not None:
            records.append(WindowRecord(
                profile_id=profile_id, session_id=session_id,
                t_start=t, t_end=t + window_s, modality="pointer",
                feats=feats,
            ))
        t += hop_s
    return records
