"""Identity Trust Graph.

Composes the four live signals into a graph of evidence nodes an agent can
reason over. Nodes are grouped in four tiers (identity/device/presence/money);
edges carry corroboration; each action carries a *policy* naming the subset of
nodes that must be lit before money may move.

  - identity  -> CRS (TransUnion TruValidate / FICO 9 / Fraud Finder)
  - device    -> Secure Enclave P-256 key + network/geo
  - presence  -> the Cadence behavioral daemon (keystroke/pointer/continuity)
  - money     -> Capital One Nessie transfer ledger

This is read-only composition; nothing here moves money or calls CRS except the
explicit `light_identity()` entrypoint (test personas only).
"""
from __future__ import annotations

import time

from gait.paths import REPO_ROOT

# --- node catalogue ---------------------------------------------------------
NODE_DEFS = [
    ("bureau_match",    "identity", "Bureau identity",     "CRS · TransUnion"),
    ("credit_file",     "identity", "Credit file · FICO",  "CRS · TransUnion"),
    ("fraud_clear",     "identity", "Fraud Finder",        "CRS · TransUnion"),
    ("device_key",      "device",   "Device-bound key",    "Secure Enclave"),
    ("network",         "device",   "Network",             "Secure Enclave"),
    ("geo",             "device",   "Location",            "Secure Enclave"),
    ("keystroke",       "presence", "Keystroke dynamics",  "Cadence daemon"),
    ("pointer",         "presence", "Pointer dynamics",    "Cadence daemon"),
    ("continuity",      "presence", "Session continuity",  "Cadence daemon"),
    ("recipient_known", "money",    "Recipient history",   "Capital One · Nessie"),
    ("amount_normal",   "money",    "Amount pattern",      "Capital One · Nessie"),
    ("velocity_normal", "money",    "Velocity",            "Capital One · Nessie"),
]
_DEF_BY_ID = {d[0]: d for d in NODE_DEFS}
IDENTITY_NODES = ("bureau_match", "credit_file", "fraud_clear")
PRESENCE_NODES = ("keystroke", "pointer", "continuity")

EDGES = [
    ("keystroke", "continuity", 0.9),
    ("pointer", "continuity", 0.75),
    ("bureau_match", "fraud_clear", 0.85),
    ("bureau_match", "credit_file", 0.8),
    ("device_key", "geo", 0.7),
    ("device_key", "network", 0.7),
    ("recipient_known", "amount_normal", 0.8),
    ("continuity", "device_key", 0.65),
    ("fraud_clear", "recipient_known", 0.6),
]

# recipients the account has paid before (seed history)
KNOWN_RECIPIENTS = {"november rent", "rent", "oakview properties", "savings",
                    "rent — november", "landlord"}

# CRS results cached in-process; filled by light_identity() / the /kyc flow
_IDENTITY_CACHE: dict = {}


def _state(conf: float, contradicted: bool = False) -> str:
    if contradicted or conf < 0.4:
        return "contradicted"
    if conf >= 0.7:
        return "lit"
    return "stale"


def _node(nid: str, conf: float, detail: str, *, contradicted: bool = False,
          state: str | None = None) -> dict:
    _id, tier, label, source = _DEF_BY_ID[nid]
    return {"id": _id, "tier": tier, "label": label, "source": source,
            "confidence": round(float(conf), 3), "detail": detail,
            "state": state or _state(conf, contradicted)}


# --- identity (CRS) ---------------------------------------------------------
def light_identity(persona_key: str = "pass") -> dict:
    """Run CRS (test personas only) and cache the three identity nodes.
    persona_key: 'pass' -> Margaret Okafor; 'fail' -> Kayla Brennan (synthetic).
    """
    from .crs import get_client, PASS_PERSONA, FAIL_PERSONA
    persona = FAIL_PERSONA if persona_key == "fail" else PASS_PERSONA
    crs = get_client()
    idv = crs.verify_identity(persona)
    credit = crs.credit_score(persona)
    fraud = crs.fraud_score(persona)
    name = f"{persona['firstName'].title()} {persona['lastName'].title()}"
    risk = fraud.get("risk")
    verified = bool(idv.get("verified"))
    fraud_bad = risk is not None and risk >= 70
    _IDENTITY_CACHE.clear()
    _IDENTITY_CACHE.update({
        "name": name, "mode": idv.get("mode", "mock"),
        "verified": verified, "score": credit.get("score"),
        "band": credit.get("band", "unknown"), "risk": risk,
        "level": fraud.get("level", "unknown"),
        "signals": fraud.get("signals", []), "t": time.time(),
    })
    return {"name": name, "nodes": _identity_nodes(), "mode": idv.get("mode"),
            "verified": verified, "fico": credit.get("score"), "fraud": risk}


def _identity_nodes() -> list[dict]:
    c = _IDENTITY_CACHE
    if not c:
        return [_node(n, 0.5, "awaiting verification", state="stale")
                for n in IDENTITY_NODES]
    verified = c.get("verified")
    risk = c.get("risk")
    fraud_bad = risk is not None and risk >= 70
    bureau = _node("bureau_match", 0.97 if verified else 0.2,
                   (f"{c['name']} · TruValidate verified" if verified
                    else "TruValidate: identity not confirmed"),
                   contradicted=not verified)
    fico = c.get("score")
    credit = _node("credit_file", 0.9 if fico and fico >= 640 else 0.45,
                   (f"FICO {fico} · {c.get('band')}" if fico
                    else "thin / no credit file"))
    fraud = _node("fraud_clear", 0.15 if fraud_bad else 0.95,
                  (f"risk {risk}/100 · {c.get('level')}"
                   + (f" · {', '.join(c['signals'][:2])}" if fraud_bad and c.get('signals') else "")),
                  contradicted=fraud_bad)
    return [bureau, credit, fraud]


# --- presence (behavioral daemon) ------------------------------------------
def _presence_nodes(presence: dict | None) -> list[dict]:
    if not presence:
        return [_node(n, 0.5, "no live signal", state="stale")
                for n in PRESENCE_NODES]
    score = float(presence.get("score", 0.0))
    mods = presence.get("modalities", {}) or {}
    keys = float(mods.get("keys", score))
    ptr = float(mods.get("pointer", score))
    bot = bool(presence.get("bot_flag"))
    age = presence.get("last_input_age_s")
    takeover = score < 0.35 or bot
    cont_detail = ("automation detected" if bot
                   else "typist changed — takeover" if score < 0.35
                   else f"continuous · {score:.0%} match")
    return [
        _node("keystroke", keys, f"{keys:.0%} match to enrolled profile",
              contradicted=takeover),
        _node("pointer", ptr, f"{ptr:.0%} match · curvature + submovement"),
        _node("continuity", score, cont_detail, contradicted=takeover),
    ]


# --- device -----------------------------------------------------------------
def _device_nodes(presence: dict | None) -> list[dict]:
    enclave = (presence or {}).get("key_backend") == "secure_enclave"
    return [
        _node("device_key", 0.98 if enclave else 0.9,
              "Secure Enclave P-256 · device-bound"),
        _node("network", 0.9, "same ASN · 14 days"),
        _node("geo", 0.88, "Berkeley, CA · home radius"),
    ]


# --- money (Nessie) ---------------------------------------------------------
def _money_nodes(action: dict | None) -> list[dict]:
    if not action:
        return [_node(n, 0.5, "no pending action", state="stale")
                for n in ("recipient_known", "amount_normal", "velocity_normal")]
    recipient = str(action.get("recipient", "")).strip().lower()
    amount = float(action.get("amount", 0) or 0)
    known = any(k in recipient or recipient in k for k in KNOWN_RECIPIENTS) if recipient else False
    rec = _node("recipient_known", 0.92 if known else 0.25,
                ("paid before · 6 prior transfers" if known
                 else "first time paying this recipient"),
                contradicted=not known)
    amt = _node("amount_normal", 0.9 if amount <= 7000 else 0.35,
                (f"${amount:,.0f} · within range" if amount <= 7000
                 else f"${amount:,.0f} · above usual"),
                contradicted=amount > 7000)
    vel = _node("velocity_normal", 0.95, "1 transfer this session")
    return [rec, amt, vel]


# --- policy / coverage ------------------------------------------------------
def required_nodes(action: dict | None) -> list[str]:
    req = list(PRESENCE_NODES) + ["device_key"]
    if not action:
        return req
    amount = float(action.get("amount", 0) or 0)
    recipient = str(action.get("recipient", "")).strip().lower()
    known = any(k in recipient or recipient in k for k in KNOWN_RECIPIENTS) if recipient else False
    if amount > 500:
        req += ["recipient_known", "amount_normal"]
    if amount > 2500:
        req += list(IDENTITY_NODES)
    if not known:
        for n in ("bureau_match", "fraud_clear"):
            if n not in req:
                req.append(n)
    # de-dup, keep order
    seen, out = set(), []
    for n in req:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _mandate(nodes_by_id: dict) -> dict:
    cont = nodes_by_id.get("continuity", {})
    active = cont.get("state") == "lit"
    name = _IDENTITY_CACHE.get("name", "Margaret Okafor")
    now = time.time()
    return {"active": active, "max_amount": 2500, "scope": "known payees",
            "root": name, "issued_at": now - 540, "expires_at": now + 2460}


def build_graph(presence: dict | None, action: dict | None = None) -> dict:
    nodes = (_identity_nodes() + _device_nodes(presence)
             + _presence_nodes(presence) + _money_nodes(action))
    by_id = {n["id"]: n for n in nodes}
    required = required_nodes(action)
    lit = [n for n in required if by_id.get(n, {}).get("state") == "lit"]
    score = float((presence or {}).get("score", 0.0)) if presence else 0.0
    return {
        "nodes": nodes,
        "edges": [{"from": a, "to": b, "strength": s} for a, b, s in EDGES],
        "mandate": _mandate(by_id),
        "presence_score": round(score, 3),
        "action": action,
        "coverage": {"required": required, "lit": lit,
                     "satisfied": len(lit) == len(required)},
    }
