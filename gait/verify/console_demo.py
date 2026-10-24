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


def next_event(store, rng: random.Random) -> None:
    """Emit one fresh plausible transaction (for the live pulse)."""
    name, fico, band, frisk, flevel = rng.choice(CUSTOMERS[1:8])  # mostly clean
    amt = rng.choice([90, 180, 420, 650, 1100, 260])
    trust = round(rng.uniform(0.83, 0.96), 2)
    store.audit(f"transfer:{amt:.2f}", "cust_" + name.lower().replace(" ", "_"),
                trust, "allow", "all signals clear", customer=name,
                amount=float(amt), trust=trust, factors=ALLOW_FACTORS)
