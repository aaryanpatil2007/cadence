"""Gait verifier: separate process, port 7800, reachable from the LAN.

Checks signature, nonce freshness/single-use, attestation expiry; applies the
score policy; audits every decision.
"""
from __future__ import annotations

import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gait.attest import jws as jws_mod
from gait.paths import REPO_ROOT
from .policy import load_policy, parse_amount
from .store import Store
from .crs import get_client, PASS_PERSONA
from .signals import device_risk, transaction_risk
from .risk import evaluate

IAT_SKEW_S = 2
CONSOLE_DIST = REPO_ROOT / "web" / "console" / "dist"


class RegisterBody(BaseModel):
    device_id: str
    pubkey_pem: str
    label: str = ""


class VerifyBody(BaseModel):
    jws: str
    action: str = "unspecified"
    payee: str = "savings"
    fingerprint: str = ""
    client_ip: str = ""
    user_agent: str = ""
    pasted_ssn: bool = False
    history: list[dict] = []


class KycBody(BaseModel):
    device_id: str
    firstName: str
    lastName: str
    ssn: str
    dob: str = ""
    street1: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""


def create_app(store: Store | None = None) -> FastAPI:
    app = FastAPI(title="gait-verifier")
    app.add_middleware(CORSMiddleware, allow_origins=["*"],
                       allow_methods=["*"], allow_headers=["*"])
    db = store or Store()

    @app.post("/register")
    def register(body: RegisterBody):
        db.register(body.device_id, body.pubkey_pem, body.label)
        db.audit("register", body.device_id, None, "ok", body.label)
        # anchor the behavioral profile to a bureau-verified identity, and
        # pull credit + fraud risk to drive risk-based limits (all CRS):
        crs = get_client()
        idv = crs.verify_identity(PASS_PERSONA)
        credit = crs.credit_score(PASS_PERSONA)
        fraud = crs.fraud_score(PASS_PERSONA)
        name = f"{PASS_PERSONA['firstName'].title()} {PASS_PERSONA['lastName'].title()}"
        db.set_identity(body.device_id, name, idv.get("verified", False), True,
                        idv.get("mode", "mock"), credit.get("score"),
                        credit.get("band", "unknown"), fraud.get("risk"),
                        fraud.get("level", "unknown"))
        db.audit("crs:anchor", body.device_id, None,
                 "ok" if idv.get("verified") else "deny",
                 f"IDV {idv.get('mode')} · FICO {credit.get('score')} "
                 f"({credit.get('band')}) · fraud {fraud.get('risk')}/100")
        return {"ok": True, "identity": db.get_identity(body.device_id)}

    @app.get("/identity/{device_id}")
    def identity(device_id: str):
        return {"identity": db.get_identity(device_id)}

    @app.post("/kyc")
    def kyc(body: KycBody):
        """Trust-ladder rung 3: live CRS TruValidate identity verification.
        Success grants a one-time, 3-minute exception for this device."""
        crs = get_client()
        result = crs.verify_identity(body.model_dump(exclude={"device_id"}))
        msgs = "; ".join(m.get("text", "") for m in result.get("messages", []))
        if result.get("verified"):
            exp = db.grant_kyc(body.device_id)
            db.audit("crs:kyc", body.device_id, None, "allow",
                     f"TruValidate verified ({result.get('mode')})")
            return {"verified": True, "mode": result.get("mode"),
                    "expires_in": int(exp - time.time())}
        db.audit("crs:kyc", body.device_id, None, "deny",
                 f"TruValidate: {msgs[:140]} ({result.get('mode')})")
        return {"verified": False, "mode": result.get("mode"),
                "messages": result.get("messages", [])}

    @app.get("/nonce")
    def nonce():
        return {"nonce": db.issue_nonce(), "expires_in": 30}

    @app.post("/verify")
    def verify(body: VerifyBody, request: Request):
        def deny(reason: str, device_id=None, score=None):
            db.audit(body.action, device_id, score, "deny", reason)
            return {"decision": "deny", "score": score, "reason": reason}

        try:
            payload = jws_mod.decode_unverified(body.jws)
        except Exception:
            return deny("malformed attestation")
        device_id = payload.get("device_id")
        score = payload.get("score")

        pem = db.get_device(device_id) if device_id else None
        if pem is None:
            return deny("unknown device", device_id, score)
        try:
            pub = serialization.load_pem_public_key(pem.encode())
            payload = jws_mod.verify(body.jws, pub)
        except Exception:
            return deny("bad signature", device_id, score)

        nonce_state = db.consume_nonce(payload.get("nonce", ""))
        if nonce_state != "ok":
            return deny(f"nonce {nonce_state}", device_id, score)

        now = time.time()
        if payload.get("exp", 0) < now:
            return deny("attestation expired", device_id, score)
        if payload.get("iat", 0) > now + IAT_SKEW_S:
            return deny("attestation from the future", device_id, score)

        amount = parse_amount(body.action)
        biometric = bool(payload.get("biometric"))
        challenge_passed = db.recent_challenge(device_id)
        kyc_passed = db.consume_kyc(device_id)

        # gather the four signals
        ip = body.client_ip or (request.client.host if request.client else "")
        device = device_risk(db, device_id, body.fingerprint, ip,
                             body.pasted_ssn, body.user_agent)
        txn = transaction_risk(body.history, amount, body.payee)
        identity = db.get_identity(device_id)

        result = evaluate(presence=float(score), amount=amount,
                          identity=identity, device=device, txn=txn,
                          biometric=biometric, kyc_passed=kyc_passed,
                          challenge_passed=challenge_passed)

        cust = (identity or {}).get("name")
        db.audit(body.action, device_id, score, result["decision"],
                 result["reason"] or result["decision"], customer=cust,
                 amount=amount, trust=result["trust"], factors=result["factors"])
        return {"decision": result["decision"], "score": score,
                "reason": result["reason"] or {
                    "allow": "all signals clear",
                    "stepup": "additional verification needed",
                    "deny": "blocked",
                }[result["decision"]],
                "recovery": result["recovery"], "trust": result["trust"],
                "factors": result["factors"], "ceiling": result["ceiling"],
                "credit_band": result["credit_band"],
                "kyc_required": result["kyc_required"],
                "challenge_passed": challenge_passed, "biometric": biometric,
                "identity": identity}

    @app.post("/challenge")
    def challenge(body: dict):
        """The client reports a completed behavioral challenge; one per
        action window — the next /verify drops the elevated bar instead of
        looping the prompt."""
        device_id = body.get("device_id", "")
        db.record_challenge(device_id)
        db.audit("challenge", device_id, None, "ok", "behavioral step-up completed")
        return {"ok": True}

    @app.get("/audit")
    def audit(limit: int = 50):
        return {"entries": db.audit_tail(limit)}

    @app.get("/policy")
    def policy():
        return load_policy()

    # ---------------- Cadence Console ----------------
    @app.get("/console/events")
    def console_events(limit: int = 40):
        return {"events": db.events(limit)}

    @app.get("/console/identities")
    def console_identities():
        return {"identities": db.identities_all()}

    @app.get("/console/stats")
    def console_stats():
        return db.stats()

    @app.get("/console/audit")
    def console_audit():
        return db.audit_chain()

    @app.post("/console/seed")
    def console_seed(n: int = 26):
        from . import console_demo
        console_demo.seed(db, n)
        return {"ok": True, **db.stats()}

    @app.get("/console/stream")
    async def console_stream(request: Request):
        import asyncio
        import json as _json
        from sse_starlette.sse import EventSourceResponse

        async def gen():
            last_id = None
            while True:
                if await request.is_disconnected():
                    break
                evs = db.events(8)
                fresh = [e for e in evs if last_id is None or e["id"] > last_id]
                if evs:
                    last_id = evs[0]["id"]
                for e in reversed(fresh):
                    yield {"event": "txn", "data": _json.dumps(e)}
                yield {"event": "stats", "data": _json.dumps(db.stats())}
                await asyncio.sleep(1.0)
        return EventSourceResponse(gen())

    # Cadence Console SPA (same origin as the API, so no CORS for console reads)
    if CONSOLE_DIST.exists():
        app.mount("/", StaticFiles(directory=CONSOLE_DIST, html=True), name="console")

    return app


def main() -> None:
    import os
    import uvicorn
    store = Store()
    app = create_app(store)
    if os.environ.get("CADENCE_DEMO") == "1":
        import random
        import threading
        from . import console_demo
        if store.stats()["total"] == 0:
            console_demo.seed(store)
            print("[verifier] demo population seeded")

        def pulse():
            rng = random.Random()
            while True:
                time.sleep(random.uniform(6, 12))
                try:
                    console_demo.next_event(store, rng)
                except Exception:
                    pass
        threading.Thread(target=pulse, daemon=True).start()
        print("[verifier] live demo pulse active")
    uvicorn.run(app, host="0.0.0.0", port=7800, log_level="warning")


if __name__ == "__main__":
    main()
