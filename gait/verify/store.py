"""Verifier persistence: devices, nonces, audit log (sqlite)."""
from __future__ import annotations

import secrets
import sqlite3
import time
from pathlib import Path

from gait.paths import data_root

NONCE_TTL_S = 30


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
            device_id TEXT, score REAL, decision TEXT, reason TEXT);
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
              decision: str, reason: str) -> None:
        self.db.execute(
            "INSERT INTO audit(ts, action, device_id, score, decision, reason) "
            "VALUES(?,?,?,?,?,?)",
            (time.time(), action, device_id, score, decision, reason))
        self.db.commit()

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
            "SELECT ts, action, device_id, score, decision, reason FROM audit "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(ts=r[0], action=r[1], device_id=r[2], score=r[3],
                     decision=r[4], reason=r[5]) for r in rows]
