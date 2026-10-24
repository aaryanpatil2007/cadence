"""Hand-built event streams -> exact expected hold/dd/ud, window gating."""
import math

from gait.features.keystroke import (
    pair_keystrokes, build_seq, extract_key_windows, keycode_class,
)
from gait.features.pointer import extract_pointer_windows
from gait.features.schema import CLS_INDEX, KEY_STAT_NAMES, POINTER_STAT_NAMES


def mk_key_events(times_codes):
    """[(t_down, t_up, keycode)] -> raw event dicts."""
    evs = []
    for td, tu, code in times_codes:
        evs.append({"t": td, "type": "down", "keycode": code,
                    "autorepeat": 0, "shift_side": None, "cmd_side": None})
        evs.append({"t": tu, "type": "up", "keycode": code,
                    "autorepeat": 0, "shift_side": None, "cmd_side": None})
    return sorted(evs, key=lambda e: e["t"])


def test_hold_dd_ud_exact():
    # key A (code 0) at t=1.0 held 0.1; key L (code 37) at t=1.3 held 0.08
    evs = mk_key_events([(1.0, 1.1, 0), (1.3, 1.38, 37)])
    strokes = pair_keystrokes(evs)
    assert len(strokes) == 2
    seq = build_seq(strokes)
    assert math.isclose(seq[1].hold, math.log1p(0.08), rel_tol=1e-9)
    assert math.isclose(seq[1].dd, math.log1p(0.3), rel_tol=1e-9)
    assert math.isclose(seq[1].ud, math.log1p(0.2 + 0.5), rel_tol=1e-9)
    assert math.isclose(seq[1].uu, math.log1p(0.28), rel_tol=1e-9)


def test_key_classes():
    assert keycode_class(0) == CLS_INDEX["letter_left_hand"]    # a
    assert keycode_class(38) == CLS_INDEX["letter_right_hand"]  # j
    assert keycode_class(49) == CLS_INDEX["space"]
    assert keycode_class(51) == CLS_INDEX["backspace"]
    assert keycode_class(36) == CLS_INDEX["enter"]
    assert keycode_class(56) == CLS_INDEX["modifier_left"]
    assert keycode_class(60) == CLS_INDEX["modifier_right"]
    assert keycode_class(123) == CLS_INDEX["arrow"]
    assert keycode_class(18) == CLS_INDEX["digit"]
    assert keycode_class(43) == CLS_INDEX["punct"]  # comma
    assert keycode_class(999) == CLS_INDEX["other"]


def test_window_min_keys_gating():
    # 5 keystrokes only -> below MIN_KEYS=8 -> no record
    evs = mk_key_events([(i * 0.2, i * 0.2 + 0.08, 0) for i in range(5)])
    recs = extract_key_windows(evs, "p", "s")
    assert recs == []
    # 12 keystrokes within 5 s -> records emitted
    evs = mk_key_events([(i * 0.3, i * 0.3 + 0.08, 0) for i in range(12)])
    recs = extract_key_windows(evs, "p", "s")
    assert len(recs) >= 1
    assert all(len(r.feats) == len(KEY_STAT_NAMES) for r in recs)
    assert all(r.modality == "keys" for r in recs)
    assert all(len(r.seq) >= 8 for r in recs)


def test_window_boundaries():
    # keystrokes at t=0..4.9 all land in the first 5 s window
    evs = mk_key_events([(i * 0.5, i * 0.5 + 0.06, 0) for i in range(10)])
    recs = extract_key_windows(evs, "p", "s")
    first = recs[0]
    assert first.t_start == 0.0 and first.t_end == 5.0


def test_pointer_gating_and_shape():
    # too few samples -> nothing
    evs = [{"t": i * 0.1, "type": "move", "x": i * 5.0, "y": 0.0} for i in range(10)]
    assert extract_pointer_windows(evs, "p", "s") == []
    # a real movement: 200 samples over 2 s, curved path + a click
    evs = []
    for i in range(200):
        t = i * 0.01
        evs.append({"t": t, "type": "move",
                    "x": 100 + 300 * t / 2 + 20 * math.sin(3 * t),
                    "y": 100 + 200 * t / 2 + 10 * math.cos(3 * t)})
    evs.append({"t": 2.05, "type": "down", "x": 400, "y": 300,
                "click_state": 1, "pressure": 0.4})
    evs.append({"t": 2.15, "type": "up", "x": 400, "y": 300})
    recs = extract_pointer_windows(evs, "p", "s")
    assert len(recs) >= 1
    r = recs[0]
    assert r.modality == "pointer"
    assert len(r.feats) == len(POINTER_STAT_NAMES)
    speed_mean = r.feats[POINTER_STAT_NAMES.index("speed_mean")]
    assert 50 < speed_mean < 1000
    dwell = r.feats[POINTER_STAT_NAMES.index("click_dwell_mean")]
    assert math.isclose(dwell, 0.1, rel_tol=1e-6)
