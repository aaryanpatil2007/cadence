"""Demo population + live event feed for the Cadence Console.

Seeds a realistic backlog of scored transactions across a set of customers and
(optionally) emits new ones over time so the console reads as a live, bustling
fraud-operations surface. The hero customer (Margaret Okafor) is the real
CRS-anchored identity; the rest are canned population so the stream has texture.
Scoring distribution mirrors the real risk engine's decision bands.
"""
from __future__ import annotations

import random
import time

# canned customer population (FICO band + fraud level shape their decisions)
CUSTOMERS = [
    ("Margaret Okafor", 790, "prime", 11, "low"),
    ("Daniel Whitfield", 812, "prime", 8, "low"),
    ("Grace Nakamura", 768, "prime", 14, "low"),
    ("Priya Venkatesan", 701, "near-prime", 22, "low"),
    ("Lauren Kowalczyk", 744, "prime", 17, "low"),
    ("Terrence Abernathy", 688, "near-prime", 31, "medium"),
    ("Elena Castellanos", 715, "near-prime", 19, "low"),
    ("Ricky Dalton", 540, "subprime", 52, "medium"),
    ("Marcus Bellamy", 612, "subprime", 44, "medium"),
    ("Kayla Brennan", 640, "subprime", 88, "high"),   # synthetic identity
]

MEMOS = ["rent", "utilities", "groceries", "payroll", "invoice #2291",
         "savings transfer", "car payment", "tuition", "supplier payment",
         "contractor", "insurance", "subscription"]

ALLOW_FACTORS = [
    {"dimension": "Presence", "label": "Recognized user", "detail": "behavioral match 94%", "severity": "ok"},
    {"dimension": "Identity", "label": "Identity verified", "detail": "TransUnion · low fraud risk", "severity": "ok"},
    {"dimension": "Device", "label": "Known device", "detail": "fingerprint matches prior session", "severity": "ok"},
    {"dimension": "Transaction", "label": "Amount in range", "detail": "fits account history", "severity": "ok"},
]
FRAUD_FACTORS = [
    {"dimension": "Presence", "label": "Not the enrolled user", "detail": "behavioral match 21%", "severity": "bad"},
    {"dimension": "Device", "label": "Datacenter / VPN IP", "detail": "cloud egress, not a home ISP", "severity": "bad"},
    {"dimension": "Transaction", "label": "Unusual amount", "detail": "far above account history", "severity": "bad"},
]
SYNTH_FACTORS = [
    {"dimension": "Identity", "label": "High fraud risk", "detail": "CRS Fraud Finder 88/100 — synthetic markers", "severity": "bad"},
    {"dimension": "Identity", "label": "Identity not verified", "detail": "SSN not associated with name", "severity": "bad"},
]


def seed(store, n: int = 26, seed: int = 7) -> None:
    """Populate the identity vault + a backlog of scored transactions."""
    rng = random.Random(seed)
    # skip Margaret (CUSTOMERS[0]) — she's the real CRS-anchored hero, added
    # live at device registration so her card reads "live bureau pull"
    population = CUSTOMERS[1:]
    for name, fico, band, frisk, flevel in population:
        dev = "cust_" + name.lower().replace(" ", "_")
        store.set_identity(dev, name, flevel != "high", True, "mock",
                           fico, band, frisk, flevel)
    now = time.time()
    for i in range(n):
        t = now - (n - i) * rng.uniform(14, 48)
        name, fico, band, frisk, flevel = rng.choice(population)
        roll = rng.random()
        if flevel == "high":
            dec, trust, amt = "deny", round(rng.uniform(0.08, 0.2), 2), rng.choice([4800, 6200, 9000])
            reason = "CRS Fraud Finder flagged a synthetic identity"
            factors = SYNTH_FACTORS + [ALLOW_FACTORS[0]]
        elif roll < 0.72:
            dec, trust = "allow", round(rng.uniform(0.82, 0.97), 2)
            amt = rng.choice([120, 240, 500, 850, 1200, 320, 75])
            reason = "all signals clear"; factors = ALLOW_FACTORS
        elif roll < 0.9:
            dec, trust = "stepup", round(rng.uniform(0.5, 0.68), 2)
            amt = rng.choice([2200, 3400, 5200, 1800])
            reason = "elevated amount — step-up verification"
            factors = [ALLOW_FACTORS[0], ALLOW_FACTORS[1],
                       {"dimension": "Transaction", "label": "New payee",
                        "detail": "first transfer to this recipient", "severity": "warn"}]
        else:
            dec, trust = "deny", round(rng.uniform(0.12, 0.34), 2)
            amt = rng.choice([900, 1500, 3000])
            reason = "behavior doesn't match the enrolled user"
            factors = FRAUD_FACTORS
        store.audit(f"transfer:{amt:.2f}", "cust_" + name.lower().replace(" ", "_"),
                    trust if dec != "deny" else round(trust, 2), dec, reason,
                    customer=name, amount=float(amt), trust=trust,
                    factors=factors, ts=t)


def _session_curve(kind: str, n: int, rng: random.Random) -> list[float]:
    """Per-window confidence timeline for a session."""
    pts = []
    if kind == "verified":
        base = rng.uniform(0.88, 0.94)
        for i in range(n):
            pts.append(round(min(0.99, max(0.74, base + rng.gauss(0, 0.03))), 3))
    elif kind == "flagged":          # enrolled user -> impostor takeover
        drop = int(n * rng.uniform(0.45, 0.6))
        for i in range(n):
            if i < drop:
                pts.append(round(min(0.98, 0.9 + rng.gauss(0, 0.03)), 3))
            else:
                k = min(1.0, (i - drop) / 3)      # collapse over ~3 windows
                pts.append(round(max(0.05, 0.9 * (1 - k) + 0.1 * k + rng.gauss(0, 0.02)), 3))
    else:                             # bot / automation
        for i in range(n):
            pts.append(round(max(0.02, 0.05 + rng.gauss(0, 0.01)), 3))
    return pts


# behavioral profiles + sessions (the recognized-user vs impostor narrative)
def profiles(store) -> list[dict]:
    rng = random.Random(11)
    out = []
    roster = [
        ("Margaret Okafor", "mac · secure enclave", 0.97, 1240, [
            ("verified", "home · known device"), ("verified", "home · known device"),
            ("flagged", "unrecognized typist · same session"), ("verified", "home · known device")]),
        ("Daniel Whitfield", "mac · secure enclave", 0.95, 1080, [
            ("verified", "office"), ("verified", "office"), ("verified", "home")]),
        ("Priya Venkatesan", "windows · platform key", 0.93, 910, [
            ("verified", "home"), ("flagged", "datacenter IP · bot timing"), ("verified", "home")]),
        ("Grace Nakamura", "mac · secure enclave", 0.96, 1160, [
            ("verified", "home"), ("verified", "travel")]),
    ]
    for name, device, auc, windows, sess in roster:
        sessions = []
        for i, (kind, note) in enumerate(sess):
            n = rng.randint(10, 18)
            sessions.append({
                "id": f"s{i}", "kind": kind, "note": note,
                "windows": n, "mean": round(sum(_session_curve(kind, n, rng)) / n, 3),
                "curve": _session_curve(kind, n, rng),
                "minutes_ago": (len(sess) - i) * rng.randint(40, 120),
            })
        out.append({"name": name, "device": device, "model_auc": auc,
                    "windows_trained": windows, "sessions": sessions,
                    "flagged": sum(1 for s in sess if s[0] != "verified")})
    return out


def alerts(store) -> list[dict]:
    """Incidents surfaced to a fraud analyst."""
    out = []
    for e in store.events(60):
        if e["decision"] == "deny":
            sev = "critical" if (e.get("trust") or 1) < 0.25 else "high"
            reason = e["reason"]
            kind = ("Synthetic identity" if "synthetic" in reason.lower() or "Fraud Finder" in reason
                    else "Account takeover" if "match" in reason.lower()
                    else "Blocked transfer")
            out.append({"ts": e["ts"], "severity": sev, "kind": kind,
                        "customer": e["customer"], "amount": e["amount"],
                        "detail": reason, "status": "open"})
    return out[:24]


def devices(store) -> list[dict]:
    rng = random.Random(5)
    base = [
        ("Margaret Okafor", "MacBook Pro · Secure Enclave", "residential", "trusted", 1),
        ("Daniel Whitfield", "MacBook Air · Secure Enclave", "residential", "trusted", 1),
        ("Priya Venkatesan", "Windows · platform key", "residential", "trusted", 1),
        ("unknown", "Linux · headless", "datacenter (AWS)", "blocked", 7),
        ("unknown", "Chrome · emulated", "VPN exit (NL)", "blocked", 4),
        ("Grace Nakamura", "MacBook Pro · Secure Enclave", "residential", "trusted", 1),
    ]
    out = []
    for owner, hw, net, trust, attempts in base:
        out.append({"owner": owner, "hardware": hw, "network": net, "trust": trust,
                    "attempts": attempts, "fp": "fp" + str(rng.integers(10**7, 10**8))})
    return out


def integrations(store) -> dict:
    from .crs import get_client
    crs = get_client()
    st = store.stats()
    return {
        "nessie": {"name": "Capital One · Nessie", "status": "live",
                   "detail": "ledger + transfers", "calls": (st["total"] or 0)},
        "crs_idv": {"name": "CRS · TransUnion TruValidate", "status": "live" if crs.live else "sandbox",
                    "detail": "identity verification", "calls": len(store.identities_all())},
        "crs_credit": {"name": "CRS · Credit (FICO 9)", "status": "live" if crs.live else "sandbox",
                       "detail": "risk-based limits", "calls": len(store.identities_all())},
        "crs_fraud": {"name": "CRS · Fraud Finder", "status": "live" if crs.live else "sandbox",
                      "detail": "synthetic-identity detection", "calls": len(store.identities_all())},
        "enclave": {"name": "Apple Secure Enclave", "status": "active",
                    "detail": "device-bound P-256 signing", "calls": None},
    }


def next_event(store, rng: random.Random) -> None:
    """Emit one fresh plausible transaction (for the live pulse)."""
    name, fico, band, frisk, flevel = rng.choice(CUSTOMERS[1:8])  # mostly clean
    amt = rng.choice([90, 180, 420, 650, 1100, 260])
    trust = round(rng.uniform(0.83, 0.96), 2)
    store.audit(f"transfer:{amt:.2f}", "cust_" + name.lower().replace(" ", "_"),
                trust, "allow", "all signals clear", customer=name,
                amount=float(amt), trust=trust, factors=ALLOW_FACTORS)
