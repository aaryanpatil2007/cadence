"""Demo bank: port 7900. A session cookie alone is NOT enough to move money —
every transfer needs a fresh gait attestation verified by the verifier.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
BANK_DIST = REPO_ROOT / "web" / "bank" / "dist"
VERIFIER_URL = os.environ.get("GAIT_VERIFIER_URL", "http://127.0.0.1:7800")
USE_NESSIE = os.environ.get("USE_NESSIE", "0") == "1"
COOKIE = "gait_session"


class TransferBody(BaseModel):
    to: str
    amount: float
    memo: str = ""
    jws: str = ""
    fingerprint: str = ""
    client_ip: str = ""
    user_agent: str = ""
    pasted_ssn: bool = False
    history: list[dict] = []


def create_app(db_path: Path | None = None, verifier_url: str = VERIFIER_URL) -> FastAPI:
    app = FastAPI(title="gait-bank")
    app.add_middleware(CORSMiddleware, allow_origins=["*"],
                       allow_methods=["*"], allow_headers=["*"],
                       allow_credentials=True)

    path = db_path or (REPO_ROOT / "data" / "bank.sqlite")
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS accounts(
        name TEXT PRIMARY KEY, balance REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS transfers(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, frm TEXT, to_ TEXT,
        amount REAL, memo TEXT, decision TEXT, score REAL, reason TEXT);
    CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, created REAL);
    """)
    if not db.execute("SELECT 1 FROM accounts").fetchone():
        db.execute("INSERT INTO accounts VALUES('checking', 12500.00)")
        db.execute("INSERT INTO accounts VALUES('savings', 48200.00)")
    db.commit()

    nessie = None
    if USE_NESSIE:
        try:
            from .nessie import Nessie
            nessie = Nessie(os.environ["NESSIE_API_KEY"])
            nessie.boot()
            print("[bank] Nessie backend active")
        except Exception as e:
            print(f"[bank] Nessie failed ({e}); using mock ledger")
            nessie = None

    def _session_ok(request: Request) -> bool:
        tok = request.cookies.get(COOKIE)
        if not tok:
            return False
        return db.execute("SELECT 1 FROM sessions WHERE token=?",
                          (tok,)).fetchone() is not None

    @app.post("/login")
    def login(response: Response):
        tok = secrets.token_urlsafe(24)
        db.execute("INSERT INTO sessions VALUES(?,?)", (tok, time.time()))
        db.commit()
        response.set_cookie(COOKIE, tok, httponly=False, samesite="lax")
        return {"ok": True, "session": tok}

    @app.get("/accounts")
    def accounts(request: Request):
        if not _session_ok(request):
            raise HTTPException(401, "not logged in")
        if nessie is not None:
            live = nessie.balances()
            if live is not None:
                return {"accounts": live, "backend": "nessie"}
        rows = db.execute("SELECT name, balance FROM accounts").fetchall()
        return {"accounts": [{"name": n, "balance": b} for n, b in rows],
                "backend": "mock"}

    @app.post("/transfer")
    def transfer(body: TransferBody, request: Request):
        if not _session_ok(request):
            raise HTTPException(401, "not logged in")
        if not body.jws:
            raise HTTPException(401, "attestation required")
        # the bank knows the account's own transfer history — pass it so the
        # risk engine can score this transfer against the user's pattern
        hist = [{"amount": r[0], "to": r[1], "ts": r[2]} for r in db.execute(
            "SELECT amount, to_, ts FROM transfers WHERE decision='allow' "
            "ORDER BY id DESC LIMIT 20").fetchall()]
        try:
            r = httpx.post(f"{verifier_url}/verify",
                           json={"jws": body.jws,
                                 "action": f"transfer:{body.amount:.2f}",
                                 "payee": body.to,
                                 "fingerprint": body.fingerprint,
                                 "client_ip": body.client_ip,
                                 "user_agent": body.user_agent,
                                 "pasted_ssn": body.pasted_ssn,
                                 "history": hist},
                           timeout=8)
            v = r.json()
        except Exception as e:
            raise HTTPException(502, f"verifier unreachable: {e}")

        decision = v.get("decision", "deny")
        score = v.get("score")
        reason = v.get("reason", "")
        db.execute(
            "INSERT INTO transfers(ts, frm, to_, amount, memo, decision, score, reason) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (time.time(), "checking", body.to, body.amount, body.memo,
             decision, score, reason))
        db.commit()

        if decision == "allow":
            applied = False
            if nessie is not None:
                try:
                    nessie.transfer(body.amount, body.memo)
                    applied = True
                except Exception as e:
                    print(f"[bank] nessie transfer failed ({e}); mock fallback")
            if not applied:
                db.execute(
                    "UPDATE accounts SET balance = balance - ? WHERE name='checking'",
                    (body.amount,))
                db.execute(
                    "UPDATE accounts SET balance = balance + ? WHERE name='savings'",
                    (body.amount,))
                db.commit()
        return {"decision": decision, "score": score, "reason": reason,
                "recovery": v.get("recovery", []), "trust": v.get("trust"),
                "factors": v.get("factors", []),
                "kyc_required": v.get("kyc_required", False),
                "ceiling": v.get("ceiling"), "credit_band": v.get("credit_band"),
                "identity": v.get("identity")}

    @app.get("/transfers")
    def transfers(limit: int = 30):
        rows = db.execute(
            "SELECT ts, frm, to_, amount, memo, decision, score, reason "
            "FROM transfers ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        local = [dict(ts=r[0], frm=r[1], to=r[2], amount=r[3], memo=r[4],
                      decision=r[5], score=r[6], reason=r[7]) for r in rows]
        # agent payments live in Nessie's ledger, not the local table
        led = nessie.ledger(limit) if nessie is not None else []
        return {"transfers": (led + local)[:limit]}

    if BANK_DIST.exists():
        app.mount("/", StaticFiles(directory=BANK_DIST, html=True), name="web")

    return app


def main() -> None:
    import uvicorn
    uvicorn.run(create_app(), host="0.0.0.0", port=7900, log_level="warning")


if __name__ == "__main__":
    main()
