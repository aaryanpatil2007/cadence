"""Gait verifier: separate process, port 7800, reachable from the LAN.

Checks signature, nonce freshness/single-use, attestation expiry; applies the
score policy; audits every decision.
"""
from __future__ import annotations

import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from gait.attest import jws as jws_mod
from .policy import load_policy, decide, parse_amount, KYC_REQUIRED_ABOVE
from .store import Store
from .crs import get_client, TEST_IDENTITY

IAT_SKEW_S = 2


class RegisterBody(BaseModel):
    device_id: str
    pubkey_pem: str
    label: str = ""


class VerifyBody(BaseModel):
    jws: str
    action: str = "unspecified"


class KycBody(BaseModel):
    device_id: str
    first_name: str
    last_name: str
    ssn: str


def create_app(store: Store | None = None) -> FastAPI:
    app = FastAPI(title="gait-verifier")
    app.add_middleware(CORSMiddleware, allow_origins=["*"],
                       allow_methods=["*"], allow_headers=["*"])
    db = store or Store()

    @app.post("/register")
    def register(body: RegisterBody):
        db.register(body.device_id, body.pubkey_pem, body.label)
        db.audit("register", body.device_id, None, "ok", body.label)
        # anchor the behavioral profile to a bureau-verified identity (CRS):
        # IDV + OFAC screen on the sandbox test identity at registration time
        crs = get_client()
        idv = crs.verify_identity(**TEST_IDENTITY)
        ofac = crs.ofac_screen(TEST_IDENTITY["first_name"],
                               TEST_IDENTITY["last_name"])
        name = f"{TEST_IDENTITY['first_name'].title()} {TEST_IDENTITY['last_name'].title()}"
        db.set_identity(body.device_id, name, idv.get("verified", False),
                        ofac.get("clear", False), idv.get("mode", "mock"))
        db.audit("crs:anchor", body.device_id, None,
                 "ok" if idv.get("verified") else "deny",
                 f"IDV {idv.get('mode')} · OFAC "
                 f"{'clear' if ofac.get('clear') else 'MATCH'}")
        return {"ok": True, "identity": db.get_identity(body.device_id)}

    @app.get("/identity/{device_id}")
    def identity(device_id: str):
        return {"identity": db.get_identity(device_id)}

    @app.post("/kyc")
    def kyc(body: KycBody):
        """Trust-ladder rung 3: live CRS identity verification. Success grants
        a one-time, 3-minute exception for this device."""
        crs = get_client()
        result = crs.verify_identity(body.first_name, body.last_name, body.ssn)
        if result.get("verified"):
            exp = db.grant_kyc(body.device_id)
            db.audit("crs:kyc", body.device_id, None, "allow",
                     f"identity verified ({result.get('mode')})")
            return {"verified": True, "mode": result.get("mode"),
                    "expires_in": int(exp - __import__('time').time())}
        db.audit("crs:kyc", body.device_id, None, "deny",
                 f"identity NOT verified ({result.get('mode')})")
        return {"verified": False, "mode": result.get("mode")}

    @app.get("/nonce")
    def nonce():
        return {"nonce": db.issue_nonce(), "expires_in": 30}

    @app.post("/verify")
    def verify(body: VerifyBody):
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
        decision, extra = decide(float(score), amount=amount)
        if decision == "stepup" and db.consume_kyc(device_id):
            decision, extra = decide(float(score), amount=amount,
                                     kyc_passed=True)
        reason = extra or {
            "allow": f"score {score} >= threshold",
            "stepup": f"score {score} in step-up band",
            "deny": f"score {score} < t_low",
        }[decision]
        db.audit(body.action, device_id, score, decision, reason)
        return {"decision": decision, "score": score, "reason": reason,
                "kyc_required": amount >= KYC_REQUIRED_ABOVE,
                "identity": db.get_identity(device_id)}

    @app.get("/audit")
    def audit(limit: int = 50):
        return {"entries": db.audit_tail(limit)}

    @app.get("/policy")
    def policy():
        return load_policy()

    return app


def main() -> None:
    import uvicorn
    uvicorn.run(create_app(), host="0.0.0.0", port=7800, log_level="warning")


if __name__ == "__main__":
    main()
