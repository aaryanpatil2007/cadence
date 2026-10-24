"""Aalto 136M keystrokes dataset -> encoder training sequences.

Per-user TSV: PARTICIPANT_ID TEST_SECTION_ID SENTENCE USER_INPUT KEYSTROKE_ID
PRESS_TIME RELEASE_TIME LETTER KEYCODE  (times in ms epoch, JS keycodes).

Output matches gait.features.schema seq rows:
[hold, dd, ud, uu, cls, bigram, shift_side, cmd_side, autorepeat]
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from gait.features.keystroke import _clip_log, _clip_log_ud
from gait.features.schema import CLS_INDEX, N_CLASSES

# JS keycode -> key class
_LEFT = set("QWERTASDFGZXCVB")
_RIGHT = set("YUIOPHJKLNM")


def js_keycode_class(code: int) -> int:
    if 65 <= code <= 90:
        ch = chr(code)
        if ch in _LEFT:
            return CLS_INDEX["letter_left_hand"]
        if ch in _RIGHT:
            return CLS_INDEX["letter_right_hand"]
        return CLS_INDEX["other"]
    if 48 <= code <= 57 or 96 <= code <= 105:
        return CLS_INDEX["digit"]
    if code == 32:
        return CLS_INDEX["space"]
    if code == 8:
        return CLS_INDEX["backspace"]
    if code == 13:
        return CLS_INDEX["enter"]
    if code in (16, 17, 18, 20):
        return CLS_INDEX["modifier_left"]  # JS can't tell sides
    if code in (91, 92, 93, 224):
        return CLS_INDEX["modifier_left"]
    if 37 <= code <= 40:
        return CLS_INDEX["arrow"]
    if code in (59, 61, 173, 186, 187, 188, 189, 190, 191, 192,
                219, 220, 221, 222):
        return CLS_INDEX["punct"]
    return CLS_INDEX["other"]


def parse_user_file(path: Path, max_len: int = 32,
                    min_len: int = 8) -> list[np.ndarray]:
    """Parse one participant file into per-sentence seq arrays (chunked to 32)."""
    sections: dict[str, list[tuple[float, float, int]]] = {}
    try:
        with open(path, errors="ignore") as f:
            header = f.readline()
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 9:
                    continue
                try:
                    press = float(parts[5]) / 1000.0
                    release = float(parts[6]) / 1000.0
                    code = int(parts[8])
                except ValueError:
                    continue
                if release < press:
                    release = press + 0.08
                sections.setdefault(parts[1], []).append((press, release, code))
    except OSError:
        return []

    out: list[np.ndarray] = []
    for strokes in sections.values():
        strokes.sort(key=lambda s: s[0])
        if len(strokes) < min_len:
            continue
        # shift intervals for shift_side flag
        shift_ivl = [(p, r) for p, r, c in strokes if c == 16]
        rows = []
        for i, (p, r, c) in enumerate(strokes):
            cls = js_keycode_class(c)
            hold = _clip_log(r - p)
            if i == 0:
                dd = ud = uu = _clip_log(0.15)
            else:
                pp, pr, _ = strokes[i - 1]
                dd = _clip_log(p - pp)
                ud = _clip_log_ud(p - pr)
                uu = _clip_log(max(r - pr, 0.0))
            prev_cls = js_keycode_class(strokes[i - 1][2]) if i else cls
            shift = 1 if any(sp <= p <= sr for sp, sr in shift_ivl) and c != 16 else 0
            rows.append([hold, dd, ud, uu, float(cls),
                         float(prev_cls * N_CLASSES + cls),
                         float(shift), 0.0, 0.0])
        # chunk long sentences into <=32-stroke sequences
        arr = np.array(rows, dtype=np.float32)
        for start in range(0, len(arr), max_len):
            chunk = arr[start:start + max_len]
            if len(chunk) >= min_len:
                out.append(chunk)
    return out


def load_users(files_dir: Path, n_users: int, seed: int = 0,
               skip: int = 0) -> dict[str, list[np.ndarray]]:
    """Sample n_users participant files (deterministic order after shuffle)."""
    rng = np.random.default_rng(seed)
    files = sorted(files_dir.glob("*_keystrokes.txt"))
    rng.shuffle(files)
    picked = files[skip:skip + n_users]
    out = {}
    for f in picked:
        seqs = parse_user_file(f)
        if len(seqs) >= 8:
            out[f.stem.split("_")[0]] = seqs
    return out
