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


# risk tiers (amount in dollars): CRS shapes the policy, not just a bolt-on
KYC_REQUIRED_ABOVE = 5000.0   # bureau-grade identity verification required
ELEVATED_ABOVE = 1000.0       # elevated band: allow needs a stronger score
ELEVATED_MARGIN = 0.10


def parse_amount(action: str) -> float:
    """Actions look like 'transfer:500.00'; anything else is amount 0."""
    if ":" in action:
        try:
            return float(action.rsplit(":", 1)[1])
        except ValueError:
            pass
    return 0.0


def decide(score: float, policy: dict | None = None, amount: float = 0.0,
           kyc_passed: bool = False, challenge_passed: bool = False,
           biometric: bool = False) -> tuple[str, str]:
    """Deterministic risk lifecycle. Returns (decision, reason).

    - kyc_passed: a one-time CRS identity verification exception is being
      spent on this action (strongest proof; clears any tier).
    - challenge_passed: a behavioral step-up was completed for this action
      window -> the elevated bar drops back to base (no challenge loops).
    - biometric: the attestation carries a hardware Touch ID confirmation ->
      clears everything below the KYC tier.
    """
    pol = policy or load_policy()
    if kyc_passed:
        return "allow", "CRS identity verified (one-time exception)"
    if score < pol["t_low"] and not biometric:
        return "deny", ""
    if amount >= KYC_REQUIRED_ABOVE:
        return "stepup", (f"amount >= ${KYC_REQUIRED_ABOVE:.0f}: "
                          "CRS identity verification required")
    if biometric:
        return "allow", "Touch ID confirmed (hardware biometric)"
    margin = 0.0 if challenge_passed else (
        ELEVATED_MARGIN if amount >= ELEVATED_ABOVE else 0.0)
    if score >= pol["t_high"] + margin:
        return ("allow", "behavioral challenge passed" if challenge_passed
                and margin == 0.0 and amount >= ELEVATED_ABOVE else "")
    return "stepup", ""
