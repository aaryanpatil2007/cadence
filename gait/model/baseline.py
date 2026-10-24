"""L0 baseline: scaled-Manhattan anomaly detector over window-stat vectors."""
from __future__ import annotations

import numpy as np


class ScaledManhattan:
    """Per-user template: mean and MAD per dim. Score = -sum(|x - mu| / s)."""

    def __init__(self):
        self.mu: np.ndarray | None = None
        self.s: np.ndarray | None = None

    def fit(self, X: np.ndarray) -> "ScaledManhattan":
        X = np.asarray(X, dtype=float)
        self.mu = np.mean(X, axis=0)
        mad = np.median(np.abs(X - np.median(X, axis=0)), axis=0)
        self.s = np.maximum(mad, 1e-3)
        return self

    def score(self, X: np.ndarray) -> np.ndarray:
        """Higher = more like the enrolled user. Shape (n,).

        Per-dim distances are capped at 10 MADs so one weird dimension
        (e.g. a zero-variance count feature) can't dominate the sum.
        """
        X = np.atleast_2d(np.asarray(X, dtype=float))
        z = np.minimum(np.abs(X - self.mu) / self.s, 10.0)
        return -np.sum(z, axis=1)

    def to_dict(self) -> dict:
        return {"mu": self.mu.tolist(), "s": self.s.tolist()}

    @staticmethod
    def from_dict(d: dict) -> "ScaledManhattan":
        m = ScaledManhattan()
        m.mu = np.array(d["mu"])
        m.s = np.array(d["s"])
        return m


def eer(genuine_scores: np.ndarray, impostor_scores: np.ndarray) -> float:
    """Equal error rate given raw detector scores (higher = genuine)."""
    thresholds = np.sort(np.concatenate([genuine_scores, impostor_scores]))
    best = 1.0
    for th in thresholds:
        frr = float(np.mean(genuine_scores < th))
        far = float(np.mean(impostor_scores >= th))
        if abs(frr - far) < best:
            best = abs(frr - far)
            best_rate = (frr + far) / 2
    return best_rate
