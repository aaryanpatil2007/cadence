"""Decision policy: score bands -> allow / stepup / deny."""
from __future__ import annotations

import json

from gait.paths import models_dir

DEFAULTS = {"t_high": 0.70, "t_low": 0.40}


def load_policy() -> dict:
    p = models_dir() / "policy.json"
    if p.exists():
        try:
            d = json.loads(p.read_text())
            return {"t_high": float(d["t_high"]), "t_low": float(d["t_low"])}
        except Exception:
            pass
    return dict(DEFAULTS)


def decide(score: float, policy: dict | None = None) -> str:
    pol = policy or load_policy()
    if score >= pol["t_high"]:
        return "allow"
    if score >= pol["t_low"]:
        return "stepup"
    return "deny"
