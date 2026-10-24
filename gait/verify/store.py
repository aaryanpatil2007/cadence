"""Verifier persistence: devices, nonces, hash-chained audit log (sqlite)."""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path

from gait.paths import data_root

NONCE_TTL_S = 30
GENESIS_HASH = "0" * 64


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or (data_root() / "verifier.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS devices(
            device_id TEXT PRIMARY KEY, pubkey_pem TEXT NOT NULL,
            label TEXT, registered_at REAL);
        CREATE TABLE IF NOT EXISTS nonces(
            nonce TEXT PRIMARY KEY, issued_at REAL NOT NULL,
            used INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS audit(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, action TEXT,
            device_id TEXT, score REAL, decision TEXT, reason TEXT,
            customer TEXT, amount REAL, trust REAL, factors TEXT,
            prev_hash TEXT, hash TEXT);
        CREATE TABLE IF NOT EXISTS identity(
            device_id TEXT PRIMARY KEY, name TEXT, verified INTEGER,
            ofac_clear INTEGER, mode TEXT, ts REAL,
            credit_score INTEGER, credit_band TEXT, fraud_risk INTEGER,
            fraud_level TEXT);
        CREATE TABLE IF NOT EXISTS fingerprints(
            device_id TEXT, fp TEXT, ip TEXT, first_seen REAL,
            PRIMARY KEY (device_id, fp));
        CREATE TABLE IF NOT EXISTS kyc_exceptions(
            device_id TEXT PRIMARY KEY, expires_at REAL);
        CREATE TABLE IF NOT EXISTS challenge_attempts(
            device_id TEXT PRIMARY KEY, ts REAL);
        """)
        self.db.commit()

    def register(self, device_id: str, pubkey_pem: str, label: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO devices VALUES(?,?,?,?)",
            (device_id, pubkey_pem, label, time.time()))
        self.db.commit()

    def get_device(self, device_id: str) -> str | None:
        row = self.db.execute(
            "SELECT pubkey_pem FROM devices WHERE device_id=?",
            (device_id,)).fetchone()
        return row[0] if row else None

    def issue_nonce(self) -> str:
        nonce = secrets.token_urlsafe(24)
        self.db.execute("INSERT INTO nonces(nonce, issued_at) VALUES(?,?)",
                        (nonce, time.time()))
        self.db.commit()
        return nonce

    def consume_nonce(self, nonce: str) -> str:
        """Returns 'ok', 'unknown', 'used', or 'expired'. Marks used on ok."""
        row = self.db.execute(
            "SELECT issued_at, used FROM nonces WHERE nonce=?",
            (nonce,)).fetchone()
        if row is None:
            return "unknown"
        issued_at, used = row
        if used:
            return "used"
        if time.time() - issued_at > NONCE_TTL_S:
            return "expired"
        self.db.execute("UPDATE nonces SET used=1 WHERE nonce=?", (nonce,))
        self.db.commit()
        return "ok"

    def audit(self, action: str, device_id: str | None, score: float | None,
              decision: str, reason: str, customer: str | None = None,
              amount: float | None = None, trust: float | None = None,
              factors: list | None = None, ts: float | None = None) -> dict:
        """Append a tamper-evident record. hash = SHA-256(prev_hash + payload),
        so any edit to history breaks the chain from that point forward."""
        ts = time.time() if ts is None else ts
        last = self.db.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = last[0] if last else GENESIS_HASH
        factors_json = json.dumps(factors or [], separators=(",", ":"))
        payload = f"{prev_hash}|{ts:.3f}|{action}|{device_id}|{customer}|" \
                  f"{amount}|{score}|{trust}|{decision}|{reason}"
        h = hashlib.sha256(payload.encode()).hexdigest()
        self.db.execute(
            "INSERT INTO audit(ts, action, device_id, score, decision, reason, "
            "customer, amount, trust, factors, prev_hash, hash) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, action, device_id, score, decision, reason, customer, amount,
             trust, factors_json, prev_hash, h))
        self.db.commit()
        return {"hash": h, "prev_hash": prev_hash, "ts": ts}

    def set_identity(self, device_id: str, name: str, verified: bool,
                     ofac_clear: bool, mode: str, credit_score: int | None,
                     credit_band: str, fraud_risk: int | None,
                     fraud_level: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO identity VALUES(?,?,?,?,?,?,?,?,?,?)",
            (device_id, name, int(verified), int(ofac_clear), mode, time.time(),
             credit_score, credit_band, fraud_risk, fraud_level))
        self.db.commit()

    def get_identity(self, device_id: str) -> dict | None:
        r = self.db.execute(
            "SELECT name, verified, ofac_clear, mode, credit_score, "
            "credit_band, fraud_risk, fraud_level FROM identity "
            "WHERE device_id=?", (device_id,)).fetchone()
        if not r:
            return None
        return {"name": r[0], "verified": bool(r[1]), "ofac_clear": bool(r[2]),
                "mode": r[3], "credit_score": r[4], "credit_band": r[5],
                "fraud_risk": r[6], "fraud_level": r[7]}

    def seen_fingerprint(self, device_id: str, fp: str, ip: str) -> bool:
        """True if this fingerprint was seen before for this device."""
        row = self.db.execute(
            "SELECT 1 FROM fingerprints WHERE device_id=? AND fp=?",
            (device_id, fp)).fetchone()
        if row:
            return True
        self.db.execute("INSERT INTO fingerprints VALUES(?,?,?,?)",
                        (device_id, fp, ip, time.time()))
        self.db.commit()
        return False

    def grant_kyc(self, device_id: str, ttl_s: float = 180) -> float:
        exp = time.time() + ttl_s
        self.db.execute(
            "INSERT OR REPLACE INTO kyc_exceptions VALUES(?,?)",
            (device_id, exp))
        self.db.commit()
        return exp

    def consume_kyc(self, device_id: str) -> bool:
        """One-time: returns True (and removes it) if a valid exception exists."""
        r = self.db.execute(
            "SELECT expires_at FROM kyc_exceptions WHERE device_id=?",
            (device_id,)).fetchone()
        if not r or r[0] < time.time():
            return False
        self.db.execute("DELETE FROM kyc_exceptions WHERE device_id=?",
                        (device_id,))
        self.db.commit()
        return True

    def record_challenge(self, device_id: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO challenge_attempts VALUES(?,?)",
            (device_id, time.time()))
        self.db.commit()

    def recent_challenge(self, device_id: str, within_s: float = 240) -> bool:
        r = self.db.execute(
            "SELECT ts FROM challenge_attempts WHERE device_id=?",
            (device_id,)).fetchone()
        return bool(r and time.time() - r[0] < within_s)

    def audit_tail(self, limit: int = 50) -> list[dict]:
        rows = self.db.execute(
            "SELECT ts, action, device_id, score, decision, reason, hash FROM audit "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(ts=r[0], action=r[1], device_id=r[2], score=r[3],
                     decision=r[4], reason=r[5], hash=r[6]) for r in rows]

    def events(self, limit: int = 40, kind: str = "transfer") -> list[dict]:
        """Rich transaction events for the Console stream (transfers only)."""
        rows = self.db.execute(
            "SELECT id, ts, customer, amount, score, trust, decision, reason, "
            "factors, hash FROM audit WHERE action LIKE ? "
            "ORDER BY id DESC LIMIT ?", (f"{kind}%", limit)).fetchall()
        out = []
        for r in rows:
            out.append(dict(id=r[0], ts=r[1], customer=r[2], amount=r[3],
                            score=r[4], trust=r[5], decision=r[6], reason=r[7],
                            factors=json.loads(r[8] or "[]"), hash=r[9]))
        return out

    def identities_all(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT name, verified, ofac_clear, mode, credit_score, credit_band, "
            "fraud_risk, fraud_level, ts FROM identity ORDER BY ts DESC").fetchall()
        return [dict(name=r[0], verified=bool(r[1]), ofac_clear=bool(r[2]),
                     mode=r[3], credit_score=r[4], credit_band=r[5],
                     fraud_risk=r[6], fraud_level=r[7], ts=r[8]) for r in rows]

    def stats(self) -> dict:
        row = self.db.execute(
            "SELECT COUNT(*), "
            "SUM(decision='allow'), SUM(decision='deny'), SUM(decision='stepup'), "
            "AVG(trust) FROM audit WHERE action LIKE 'transfer%'").fetchone()
        total = row[0] or 0
        return {"total": total, "allowed": row[1] or 0, "denied": row[2] or 0,
                "stepup": row[3] or 0,
                "avg_trust": round(row[4], 3) if row[4] is not None else None,
                "approval_rate": round((row[1] or 0) / total, 3) if total else None}

    def audit_chain(self) -> dict:
        """Full chain oldest-first + a verification result (for export)."""
        rows = self.db.execute(
            "SELECT id, ts, action, device_id, customer, amount, score, trust, "
            "decision, reason, prev_hash, hash FROM audit ORDER BY id ASC").fetchall()
        chain, prev, intact = [], GENESIS_HASH, True
        for r in rows:
            payload = f"{r[10]}|{r[1]:.3f}|{r[2]}|{r[3]}|{r[4]}|{r[5]}|{r[6]}|{r[7]}|{r[8]}|{r[9]}"
            recomputed = hashlib.sha256(payload.encode()).hexdigest()
            ok = (r[10] == prev) and (recomputed == r[11])
            intact = intact and ok
            chain.append(dict(seq=r[0], ts=r[1], action=r[2], customer=r[4],
                              amount=r[5], decision=r[8], reason=r[9],
                              prev_hash=r[10], hash=r[11], valid=ok))
            prev = r[11]
        return {"intact": intact, "length": len(chain), "entries": chain}
