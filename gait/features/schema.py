"""Feature record schema. These records are the ONLY thing ever persisted.

Privacy invariant: no raw keycodes, characters, or text appear in any record.
Keystrokes are reduced to coarse key classes (left/right-hand letter, digit,
space, punct, backspace, enter, modifier side, arrow, other) plus timing.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal
import json

# Key classes (the only key-identity information retained anywhere)
KEY_CLASSES = [
    "letter_left_hand",
    "letter_right_hand",
    "digit",
    "space",
    "punct",
    "backspace",
    "enter",
    "modifier_left",
    "modifier_right",
    "arrow",
    "other",
]
N_CLASSES = len(KEY_CLASSES)  # 11
N_BIGRAMS = N_CLASSES * N_CLASSES  # 121

CLS_INDEX = {name: i for i, name in enumerate(KEY_CLASSES)}

# Window parameters (seconds)
WINDOW_S = 5.0
HOP_S = 2.5
MIN_KEYS = 8
MIN_POINTER_SAMPLES = 40
MIN_CLICKS = 2
MIN_SCROLLS = 10

# Per-window keystroke stats feature names (§5.2)
KEY_STAT_NAMES = [
    "hold_mean", "hold_std", "hold_median",
    "dd_mean", "dd_std", "dd_median",
    "ud_mean", "ud_std", "ud_median",
    "typing_rate", "backspace_ratio",
    "shift_l_ratio", "cmd_shortcut_count",
    "burst_count", "burst_len_mean",
]

# Per-window pointer stats feature names (§5.3)
POINTER_STAT_NAMES = [
    "speed_mean", "speed_std", "speed_max",
    "accel_mean", "accel_std", "jerk_mean",
    "curvature_mean", "curvature_std",
    "straightness_mean", "straightness_std",
    "move_duration_mean", "submovement_mean",
    "overshoot_ratio_mean",
    "click_dwell_mean", "double_click_interval",
    "pressure_mean", "pressure_max",
    "scroll_rate", "scroll_delta_mean",
    "scroll_momentum_frac", "scroll_reversal_rate", "scroll_continuous",
    "idle_jitter_std",
    "n_movements", "n_clicks",
]


@dataclass
class KeySeqItem:
    """One keystroke in a window sequence (encoder input). Timing + class only."""
    hold: float
    dd: float
    ud: float
    uu: float
    cls: int          # index into KEY_CLASSES
    bigram: int       # cls_prev * 11 + cls_cur
    shift_side: int   # 0 none, 1 L, 2 R
    cmd_side: int     # 0 none, 1 L, 2 R
    autorepeat: int   # 0/1


@dataclass
class WindowRecord:
    profile_id: str
    session_id: str
    t_start: float
    t_end: float
    modality: Literal["keys", "pointer"]
    feats: list[float]
    seq: list[list[float]] = field(default_factory=list)  # keys only: KeySeqItem rows

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @staticmethod
    def from_json(line: str) -> "WindowRecord":
        d = json.loads(line)
        return WindowRecord(**d)


def seq_item_to_row(it: KeySeqItem) -> list[float]:
    return [it.hold, it.dd, it.ud, it.uu, float(it.cls), float(it.bigram),
            float(it.shift_side), float(it.cmd_side), float(it.autorepeat)]
