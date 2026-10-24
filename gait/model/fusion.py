"""Calibrated fusion + EWMA rolling score + idle decay + robotic hard floor."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

TAU_S = 4.0
IDLE_GRACE_S = 15.0
IDLE_DECAY_S = 20.0
BOT_FLOOR_P = 0.02
BOT_COV_THRESHOLD = 0.05
BOT_STRAIGHTNESS = 0.98


@dataclass
class Calibration:
    """Logistic mapping raw model score -> probability: 1/(1+exp(-(a*x+b)))."""
    a: float
    b: float

    def __call__(self, x: float) -> float:
        return 1.0 / (1.0 + math.exp(-(self.a * x + self.b)))


def fit_calibration(genuine: np.ndarray, impostor: np.ndarray,
                    trim_genuine: float = 0.0) -> Calibration:
    """Fit logistic regression on 1-d scores (genuine=1, impostor=0).

    trim_genuine drops that fraction of the LOWEST genuine scores before
    fitting: a few pathological genuine windows (pauses, corrections) flatten
    the curve and gift borderline impostors ~0.5; the EWMA absorbs the
    occasional rejected genuine window instead."""
    from sklearn.linear_model import LogisticRegression
    if trim_genuine > 0 and len(genuine) >= 10:
        cut = np.quantile(genuine, trim_genuine)
        genuine = genuine[genuine >= cut]
    X = np.concatenate([genuine, impostor]).reshape(-1, 1)
    y = np.concatenate([np.ones(len(genuine)), np.zeros(len(impostor))])
    # near-unregularized + balanced: small genuine sets must still reach p~1
    lr = LogisticRegression(C=1000.0, class_weight="balanced", max_iter=2000).fit(X, y)
    return Calibration(a=float(lr.coef_[0][0]), b=float(lr.intercept_[0]))


def robotic_keys(holds_s: list[float], dds_s: list[float]) -> bool:
    """Timing coefficient-of-variation < 0.05 => machine-regular typing."""
    for vals in (holds_s, dds_s):
        v = np.asarray(vals)
        if len(v) >= 5 and v.mean() > 1e-6 and (v.std() / v.mean()) < BOT_COV_THRESHOLD:
            return True
    return False


def robotic_pointer(straightness_mean: float, submovement_mean: float,
                    n_movements: float) -> bool:
    return (n_movements >= 1 and straightness_mean > BOT_STRAIGHTNESS
            and submovement_mean <= 1.0)


POINTER_W_CAP = 0.5  # pointer is a liveness channel, not the primary discriminator


def fuse(p_k: float | None, n_keys: int, p_m: float | None,
         n_pointer: int, bot: bool) -> tuple[float | None, float]:
    """Weighted fusion of calibrated modality probabilities (§6.4).

    Returns (fused probability, evidence weight in [0, 1.5]). Pointer weight
    is capped at 0.5: typing dynamics separate people far more reliably than
    cursor stats, so keystrokes keep authority whenever both are present, and
    pointer-only windows update the rolling score at reduced rate.
    """
    if bot:
        return BOT_FLOOR_P, 1.5
    w_k = min(1.0, n_keys / 16) if p_k is not None else 0.0
    w_m = min(POINTER_W_CAP, n_pointer / 200) if p_m is not None else 0.0
    if w_k + w_m == 0:
        return None, 0.0
    p = ((w_k * (p_k or 0.0)) + (w_m * (p_m or 0.0))) / (w_k + w_m)
    return p, w_k + w_m


class RollingScore:
    def __init__(self, tau_s: float = TAU_S):
        self.tau_s = tau_s
        self.S: float | None = None
        self._last_decay_t: float | None = None
        self._last_p: float | None = None

    def update(self, p: float, hop_s: float, weight: float = 1.0) -> float:
        """EWMA update; `weight` scales the effective rate so thin evidence
        (e.g. pointer-only windows) moves the score more slowly.

        Dynamics tuned from live testing:
        - STRONG genuine evidence (p >= 0.85) builds at full rate — the real
          user shouldn't wait 15s for a short memo to authorize; weaker
          upward evidence rises at 0.85x so borderline impostors can't vault.
        - A single outlier window can't crater the score: a big drop applies
          at half rate once, and at full rate only when a SECOND consecutive
          window agrees. Impostors and bots are consistently low, so takeover
          detection stays fast; one correction-heavy genuine window doesn't
          throw the user into the step-up band."""
        w = min(max(weight, 0.0), 1.5)
        if self.S is not None:
            if p > self.S and p < 0.85:
                w *= 0.85
            elif p < self.S - 0.3:
                prev_agreed = (self._last_p is not None
                               and self._last_p < self.S - 0.3)
                if not prev_agreed:
                    w *= 0.5
        alpha = 1.0 - math.exp(-hop_s * w / self.tau_s)
        self.S = p if self.S is None else alpha * p + (1 - alpha) * self.S
        self._last_p = p
        return self.S

    def apply_idle(self, idle_s: float, now: float) -> float | None:
        """Decay S for idle time beyond the grace period (incremental)."""
        if self.S is None or idle_s <= IDLE_GRACE_S:
            self._last_decay_t = None
            return self.S
        if self._last_decay_t is None:
            self._last_decay_t = now - (idle_s - IDLE_GRACE_S)
        dt = now - self._last_decay_t
        if dt > 0:
            self.S *= math.exp(-dt / IDLE_DECAY_S)
            self._last_decay_t = now
        return self.S
