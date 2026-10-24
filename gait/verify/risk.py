"""The fusion engine: combine four signals into one explainable decision.

  PRESENCE   — behavioral biometric score (is a verified human here?)
  IDENTITY   — CRS bureau IDV + Fraud Finder (is this a real, non-synthetic
               person?)
  DEVICE     — device/network risk (new device, datacenter IP, pasted SSN)
  TRANSACTION— anomaly vs the account's own history (amount, payee, velocity)

Output is a decision plus a ranked factor list (explainable AI / observability)
and a deterministic recovery path — never a dead-end loop.
"""
from __future__ import annotations

from .policy import (load_policy, KYC_REQUIRED_ABOVE, ELEVATED_ABOVE,
                     ELEVATED_MARGIN)

# credit band -> per-transaction ceiling (risk-based limits from CRS)
CREDIT_CEILING = {
    "prime": 25000, "near-prime": 10000, "subprime": 2500,
    "deep-subprime": 1000, "no-file": 1000, "unknown": 5000,
}
FRAUD_BLOCK_LEVEL = "high"   # CRS Fraud Finder: synthetic/high-risk identity


def evaluate(*, presence: float, amount: float, identity: dict | None,
             device: dict, txn: dict, biometric: bool, kyc_passed: bool,
             challenge_passed: bool, policy: dict | None = None) -> dict:
    pol = policy or load_policy()
    factors: list[dict] = []

    # --- presence (behavior) ---
    if presence >= pol["t_high"]:
        factors.append({"dimension": "Presence", "label": "Recognized user",
                        "detail": f"behavioral match {presence:.0%}", "severity": "ok"})
    elif presence >= pol["t_low"]:
        factors.append({"dimension": "Presence", "label": "Uncertain presence",
                        "detail": f"behavioral match {presence:.0%}", "severity": "warn"})
    else:
        factors.append({"dimension": "Presence", "label": "Not the enrolled user",
                        "detail": f"behavioral match {presence:.0%}", "severity": "bad"})

    # --- identity (CRS) ---
    fraud_block = False
    if identity:
        if identity.get("verified"):
            factors.append({"dimension": "Identity", "label": "Identity verified",
                            "detail": f"{identity.get('name','')} · "
                                      f"TransUnion ({identity.get('mode')})",
                            "severity": "ok"})
        else:
            factors.append({"dimension": "Identity", "label": "Identity not verified",
                            "detail": "bureau IDV did not pass", "severity": "bad"})
        fl = identity.get("fraud_level")
        fr = identity.get("fraud_risk")
        if fl == FRAUD_BLOCK_LEVEL:
            fraud_block = True
            factors.append({"dimension": "Identity", "label": "High fraud risk",
                            "detail": f"CRS Fraud Finder risk {fr}/100 — synthetic-identity markers",
                            "severity": "bad"})
        elif fl == "medium":
            factors.append({"dimension": "Identity", "label": "Elevated fraud risk",
                            "detail": f"CRS Fraud Finder risk {fr}/100", "severity": "warn"})
        elif fl == "low":
            factors.append({"dimension": "Identity", "label": "Low fraud risk",
                            "detail": f"CRS Fraud Finder risk {fr}/100", "severity": "ok"})

    # --- device/network ---
    for f in device.get("factors", []):
        factors.append({"dimension": "Device", **f})
    # --- transaction ---
    for f in txn.get("factors", []):
        factors.append({"dimension": "Transaction", **f})

    # --- credit-based ceiling (CRS) ---
    band = (identity or {}).get("credit_band", "unknown")
    ceiling = CREDIT_CEILING.get(band, 5000)
    over_ceiling = amount > ceiling
    if over_ceiling:
        factors.append({"dimension": "Transaction", "label": "Over account limit",
                        "detail": f"${amount:,.0f} exceeds the ${ceiling:,.0f} limit "
                                  f"for a {band} profile", "severity": "bad"})

    # --- decision ---
    device_risk = device.get("risk", 0.0)
    txn_risk = txn.get("risk", 0.0)
    # composite external risk (identity fraud handled as a hard gate above)
    ext_risk = min(1.0, device_risk + txn_risk)

    decision, reason, recovery = _decide(
        pol, presence, amount, biometric, kyc_passed, challenge_passed,
        fraud_block, over_ceiling, ext_risk)

    # trust is a presentation scalar: presence tempered by external risk
    trust = round(max(0.0, min(1.0, presence * (1 - 0.5 * ext_risk))), 3)
    severity_rank = {"bad": 0, "warn": 1, "ok": 2}
    factors.sort(key=lambda f: severity_rank.get(f["severity"], 3))
    return {"decision": decision, "reason": reason, "recovery": recovery,
            "trust": trust, "factors": factors, "ceiling": ceiling,
            "credit_band": band, "ext_risk": round(ext_risk, 3),
            "kyc_required": amount >= KYC_REQUIRED_ABOVE or over_ceiling}


def _decide(pol, presence, amount, biometric, kyc_passed, challenge_passed,
            fraud_block, over_ceiling, ext_risk) -> tuple[str, str, list[str]]:
    # 1. synthetic-identity / high fraud risk is a hard stop — no recovery
    if fraud_block:
        return "deny", "CRS Fraud Finder flagged a high-risk / synthetic identity", []
    # 2. KYC exception (spent) clears everything that isn't a fraud block
    if kyc_passed:
        return "allow", "CRS identity verified (one-time exception)", []
    # 3. amount over the credit-based ceiling OR the hard KYC floor -> bureau rung
    if over_ceiling or amount >= KYC_REQUIRED_ABOVE:
        why = ("exceeds this profile's limit" if over_ceiling
               else f"over ${KYC_REQUIRED_ABOVE:.0f}")
        return "stepup", f"amount {why}: CRS identity verification required", ["kyc"]
    # 4. presence floor (unless hardware biometric vouches)
    if presence < pol["t_low"] and not biometric:
        return "deny", "behavior doesn't match the enrolled user", ["touchid", "kyc"]
    # 5. high external risk forces step-up even with good presence
    if ext_risk >= 0.5 and not biometric:
        return "stepup", "device or transaction looks risky — confirm it's you", \
            (["touchid", "kyc"] if challenge_passed else ["challenge", "touchid"])
    # 6. biometric vouch clears the mid-tiers
    if biometric:
        return "allow", "Touch ID confirmed (hardware biometric)", []
    # 7. amount/presence bar (elevated amounts need a stronger score)
    margin = 0.0 if challenge_passed else (
        ELEVATED_MARGIN if amount >= ELEVATED_ABOVE else 0.0)
    if presence >= pol["t_high"] + margin:
        return "allow", ("behavioral challenge passed"
                         if challenge_passed and amount >= ELEVATED_ABOVE else ""), []
    return "stepup", "", (["touchid", "kyc"] if challenge_passed
                          else ["challenge", "touchid"])
