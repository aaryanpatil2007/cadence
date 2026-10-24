"""Central data paths; override root with GAIT_DATA_DIR (tests use this)."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def data_root() -> Path:
    return Path(os.environ.get("GAIT_DATA_DIR", REPO_ROOT / "data"))


def enroll_dir() -> Path:
    return data_root() / "enroll"


def models_dir() -> Path:
    d = data_root() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d
