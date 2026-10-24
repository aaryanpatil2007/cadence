"""Device/network and transaction risk signals for the fusion engine.

Each returns {risk: 0..1, factors: [{label, detail, severity}]} where
severity is "ok" | "warn" | "bad". Risk is additive evidence of fraud
(0 = clean, 1 = certain fraud); the risk engine fuses it with behavioral
presence and CRS identity.
"""
from __future__ import annotations

import ipaddress

# Small set of well-known datacenter/cloud egress prefixes (demo-grade; a real
# deployment would use an IP intelligence feed). Legit users rarely bank from
# these.
_DATACENTER_PREFIXES = [
    "198.51.100.",  # TEST-NET-2, used by the CRS synthetic persona
    "203.0.113.",   # TEST-NET-3 (CRS prime persona uses .11 — treat as clean home IP)
    "34.", "35.",   # GCP
    "52.", "54.", "3.",  # AWS
    "20.", "40.",   # Azure
]
_KNOWN_GOOD_IPS = {"203.0.113.11"}  # the anchored persona's home IP


def _ip_is_datacenter(ip: str) -> bool:
    if ip in _KNOWN_GOOD_IPS:
        return False
    return any(ip.startswith(p) for p in _DATACENTER_PREFIXES)


def device_risk(store, device_id: str, fp: str, ip: str,
                pasted_sensitive: bool, ua: str = "") -> dict:
    factors = []
    risk = 0.0

    if fp:
        new_device = not store.seen_fingerprint(device_id, fp, ip)
        if new_device:
            risk += 0.25
            factors.append({"label": "New device",
                            "detail": "first time we've seen this browser fingerprint",
                            "severity": "warn"})
        else:
            factors.append({"label": "Known device",
                            "detail": "fingerprint matches a prior session",
                            "severity": "ok"})

    if ip and _ip_is_datacenter(ip):
        risk += 0.5
        factors.append({"label": "Datacenter / VPN IP",
                        "detail": f"{ip} resolves to cloud/proxy space, not a home ISP",
                        "severity": "bad"})
    elif ip:
        factors.append({"label": "Network",
                        "detail": f"{ip} looks like a residential connection",
                        "severity": "ok"})

    if pasted_sensitive:
        risk += 0.4
        factors.append({"label": "Pasted identity data",
                        "detail": "SSN was pasted, not typed — a synthetic-identity tell",
                        "severity": "bad"})

    return {"risk": min(risk, 1.0), "factors": factors}


def transaction_risk(history: list[dict], amount: float, payee: str) -> dict:
    """history: list of prior transfers [{amount, to, ts}]. Scores this
    transfer against the account's own pattern."""
    factors = []
    risk = 0.0
    amounts = [h["amount"] for h in history]
    payees = {h.get("to") for h in history}

    if amounts:
        typical = sorted(amounts)[len(amounts) // 2]
        hi = max(amounts)
        if amount > max(hi * 2, typical * 5) and amount > 1000:
            risk += 0.45
            factors.append({"label": "Unusual amount",
                            "detail": f"${amount:,.0f} vs your usual ~${typical:,.0f} "
                                      f"(max ${hi:,.0f})", "severity": "bad"})
        else:
            factors.append({"label": "Amount in range",
                            "detail": f"${amount:,.0f} fits your history",
                            "severity": "ok"})
    else:
        factors.append({"label": "No history yet",
                        "detail": "first transfer on this account",
                        "severity": "warn"})
        if amount > 2000:
            risk += 0.2

    if payees and payee not in payees:
        risk += 0.25
        factors.append({"label": "New payee",
                        "detail": f"you've never sent to “{payee}” before",
                        "severity": "warn"})
    elif payees:
        factors.append({"label": "Known payee",
                        "detail": f"“{payee}” is a prior recipient",
                        "severity": "ok"})

    # velocity: many transfers in the recent window
    import time
    now = time.time()
    recent = [h for h in history if now - h.get("ts", 0) < 300]
    if len(recent) >= 3:
        risk += 0.3
        factors.append({"label": "High velocity",
                        "detail": f"{len(recent)} transfers in the last 5 min",
                        "severity": "bad"})

    return {"risk": min(risk, 1.0), "factors": factors}
