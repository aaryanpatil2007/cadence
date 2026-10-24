"""Keystroke feature extraction: raw key events -> per-window records.

Raw events (with keycodes) exist only in RAM inside this module's inputs;
emitted records contain coarse key classes and timing only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .schema import (
    CLS_INDEX, N_CLASSES, KeySeqItem, WindowRecord, seq_item_to_row,
    MIN_KEYS, KEY_STAT_NAMES,
)

# macOS virtual keycodes (ANSI layout) -> key class name
_LEFT_LETTERS = {12: "q", 13: "w", 14: "e", 15: "r", 17: "t",
                 0: "a", 1: "s", 2: "d", 3: "f", 5: "g",
                 6: "z", 7: "x", 8: "c", 9: "v", 11: "b"}
_RIGHT_LETTERS = {16: "y", 32: "u", 34: "i", 31: "o", 35: "p",
                  4: "h", 38: "j", 40: "k", 37: "l",
                  45: "n", 46: "m"}
_DIGITS = {18, 19, 20, 21, 22, 23, 25, 26, 28, 29}
_PUNCT = {24, 27, 30, 33, 39, 41, 42, 43, 44, 47, 50}
_ARROWS = {123, 124, 125, 126}
_MOD_LEFT = {55, 56, 58, 59}    # LCmd, LShift, LOpt, LCtrl
_MOD_RIGHT = {54, 60, 61, 62}   # RCmd, RShift, ROpt, RCtrl

KEYCODE_SIDE = {56: "L", 60: "R", 55: "L", 54: "R", 58: "L", 61: "R", 59: "L", 62: "R"}


def keycode_class(code: int) -> int:
    if code in _LEFT_LETTERS:
        return CLS_INDEX["letter_left_hand"]
    if code in _RIGHT_LETTERS:
        return CLS_INDEX["letter_right_hand"]
    if code in _DIGITS:
        return CLS_INDEX["digit"]
    if code == 49:
        return CLS_INDEX["space"]
    if code in _PUNCT:
        return CLS_INDEX["punct"]
    if code == 51:
        return CLS_INDEX["backspace"]
    if code in (36, 76):
        return CLS_INDEX["enter"]
    if code in _MOD_LEFT:
        return CLS_INDEX["modifier_left"]
    if code in _MOD_RIGHT:
        return CLS_INDEX["modifier_right"]
    if code in _ARROWS:
        return CLS_INDEX["arrow"]
    return CLS_INDEX["other"]


@dataclass
class KeyStroke:
    """A completed keystroke (down+up paired). RAM only."""
    t_down: float
    t_up: float
    cls: int
    shift_side: int  # 0/1/2
    cmd_side: int
    autorepeat: int
    is_backspace: bool
    is_cmd_shortcut: bool


def _clip_log(x: float, lo: float = 0.0, hi: float = 2.0) -> float:
    return math.log1p(min(max(x, lo), hi))


def _clip_log_ud(x: float) -> float:
    # ud can be negative (key overlap); clip to [-0.5, 2.0], shift +0.5 then log1p
    return math.log1p(min(max(x, -0.5), 2.0) + 0.5)


def pair_keystrokes(events: list[dict]) -> list[KeyStroke]:
    """Pair keyDown/keyUp raw events into KeyStroke objects.

    Each event: {t, type: 'down'|'up', keycode, shift_side, cmd_side, autorepeat}.
    Unmatched downs get a synthetic 80 ms hold.
    """
    strokes: list[KeyStroke] = []
    pending: dict[int, dict] = {}
    for ev in events:
        code = ev["keycode"]
        if ev["type"] == "down":
            if code in pending:  # autorepeat or lost up: flush previous
                p = pending.pop(code)
                strokes.append(_mk_stroke(p, p["t"] + 0.08))
            pending[code] = ev
        elif ev["type"] == "up":
            p = pending.pop(code, None)
            if p is not None:
                strokes.append(_mk_stroke(p, ev["t"]))
    for p in pending.values():
        strokes.append(_mk_stroke(p, p["t"] + 0.08))
    strokes.sort(key=lambda s: s.t_down)
    return strokes


def _side_code(side: str | None) -> int:
    return {"L": 1, "R": 2}.get(side or "", 0)


def _mk_stroke(down_ev: dict, t_up: float) -> KeyStroke:
    code = down_ev["keycode"]
    cls = keycode_class(code)
    cmd_side = _side_code(down_ev.get("cmd_side"))
    return KeyStroke(
        t_down=down_ev["t"], t_up=t_up, cls=cls,
        shift_side=_side_code(down_ev.get("shift_side")),
        cmd_side=cmd_side,
        autorepeat=int(bool(down_ev.get("autorepeat"))),
        is_backspace=(cls == CLS_INDEX["backspace"]),
        is_cmd_shortcut=(cmd_side != 0 and cls not in
                         (CLS_INDEX["modifier_left"], CLS_INDEX["modifier_right"])),
    )


def build_seq(strokes: list[KeyStroke]) -> list[KeySeqItem]:
    """Per-keystroke sequence features (§5.1) for a window."""
    items: list[KeySeqItem] = []
    for i, s in enumerate(strokes):
        hold = _clip_log(s.t_up - s.t_down)
        if i == 0:
            dd = ud = uu = _clip_log(0.15)  # neutral priors for first key
        else:
            p = strokes[i - 1]
            dd = _clip_log(s.t_down - p.t_down)
            ud = _clip_log_ud(s.t_down - p.t_up)
            uu = _clip_log(max(s.t_up - p.t_up, 0.0))
        prev_cls = strokes[i - 1].cls if i > 0 else s.cls
        items.append(KeySeqItem(
            hold=hold, dd=dd, ud=ud, uu=uu, cls=s.cls,
            bigram=prev_cls * N_CLASSES + s.cls,
            shift_side=s.shift_side, cmd_side=s.cmd_side,
            autorepeat=s.autorepeat,
        ))
    return items


def window_stats(strokes: list[KeyStroke], window_s: float) -> list[float]:
    """Per-window keystroke stats vector (§5.2), raw seconds (not log)."""
    holds = np.array([s.t_up - s.t_down for s in strokes])
    dds = np.array([strokes[i].t_down - strokes[i - 1].t_down
                    for i in range(1, len(strokes))]) if len(strokes) > 1 else np.array([0.15])
    uds = np.array([strokes[i].t_down - strokes[i - 1].t_up
                    for i in range(1, len(strokes))]) if len(strokes) > 1 else np.array([0.05])
    n = len(strokes)
    backspaces = sum(s.is_backspace for s in strokes)
    shift_l = sum(1 for s in strokes if s.shift_side == 1)
    shift_r = sum(1 for s in strokes if s.shift_side == 2)
    shift_total = shift_l + shift_r
    cmd_shortcuts = sum(s.is_cmd_shortcut for s in strokes)

    # bursts: split on inter-key gaps > 0.6 s
    bursts, cur = [], 1
    for g in dds:
        if g > 0.6:
            bursts.append(cur)
            cur = 1
        else:
            cur += 1
    bursts.append(cur)

    def st(a):
        return [float(np.mean(a)), float(np.std(a)), float(np.median(a))]

    feats = (
        st(holds) + st(dds) + st(uds)
        + [n / window_s,
           backspaces / n,
           (shift_l / shift_total) if shift_total else 0.5,
           float(cmd_shortcuts),
           float(len(bursts)),
           float(np.mean(bursts))]
    )
    assert len(feats) == len(KEY_STAT_NAMES)
    return feats


def extract_key_windows(
    events: list[dict], profile_id: str, session_id: str,
    window_s: float = 5.0, hop_s: float = 2.5,
) -> list[WindowRecord]:
    """Slide windows over raw key events, emit records for windows with >= MIN_KEYS."""
    strokes = pair_keystrokes(events)
    if not strokes:
        return []
    t0 = strokes[0].t_down
    t_last = strokes[-1].t_down
    records = []
    t = t0
    while t <= t_last + 1e-9:
        win = [s for s in strokes if t <= s.t_down < t + window_s]
        if len(win) >= MIN_KEYS:
            seq = build_seq(win)[-32:]
            records.append(WindowRecord(
                profile_id=profile_id, session_id=session_id,
                t_start=t, t_end=t + window_s, modality="keys",
                feats=window_stats(win, window_s),
                seq=[seq_item_to_row(it) for it in seq],
            ))
        t += hop_s
    return records
