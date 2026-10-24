"""Balabit Mouse Dynamics Challenge -> gait pointer windows.

Session CSVs: record timestamp,client timestamp,button,state,x,y
States: Move, Pressed, Released, Drag; timestamps in seconds (float).
Used as population negatives for the pointer model.
"""
from __future__ import annotations

import csv
from pathlib import Path

from gait.features.pointer import extract_pointer_windows
from gait.features.schema import WindowRecord


def parse_session(path: Path) -> list[dict]:
    events = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                t = float(row["client timestamp"])
                x, y = float(row["x"]), float(row["y"])
            except (ValueError, KeyError):
                continue
            if x > 4000 or y > 4000:  # dataset glitch values
                continue
            state = row.get("state", "")
            if state == "Move":
                events.append({"t": t, "type": "move", "x": x, "y": y})
            elif state == "Drag":
                events.append({"t": t, "type": "drag", "x": x, "y": y})
            elif state == "Pressed":
                events.append({"t": t, "type": "down", "x": x, "y": y,
                               "click_state": 1, "pressure": 0.0})
            elif state == "Released":
                events.append({"t": t, "type": "up", "x": x, "y": y})
    return events


def convert(balabit_root: Path, max_sessions_per_user: int = 4,
            max_users: int = 10) -> dict[str, list[WindowRecord]]:
    """Returns {profile_id: [pointer WindowRecords]} from training_files/."""
    out: dict[str, list[WindowRecord]] = {}
    train_dir = balabit_root / "training_files"
    for user_dir in sorted(train_dir.iterdir())[:max_users]:
        if not user_dir.is_dir():
            continue
        pid = f"balabit_{user_dir.name}"
        recs: list[WindowRecord] = []
        for sess in sorted(user_dir.iterdir())[:max_sessions_per_user]:
            events = parse_session(sess)
            if len(events) < 100:
                continue
            recs.extend(extract_pointer_windows(events, pid, sess.name))
        if recs:
            out[pid] = recs
    return out
