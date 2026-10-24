"""CRS (StitchCredit sandbox) client: identity verification for the trust
ladder's top rung, plus OFAC screening at device registration.

Base: https://api-sandbox.stitchcredit.com/api
Auth: POST /users/login {email, password} -> {token}
Runs in mock mode when CRS_EMAIL/CRS_PASSWORD are absent, so the demo never
blocks on the sandbox. Every response carries "mode": "live" | "mock".

Only CRS-provided TEST identities are ever sent (hackathon rule).
"""
from __future__ import annotations

import os
import time

import httpx

BASE = os.environ.get("CRS_BASE", "https://api-sandbox.stitchcredit.com/api")

# CRS sandbox test identity (from their public docs page) — demo subject
TEST_IDENTITY = {
    "first_name": "KYLIA",
    "last_name": "PAOLIMELLI",
    "ssn": "666285642",
}


class CRSClient:
    def __init__(self):
        self.email = os.environ.get("CRS_EMAIL", "")
        self.password = os.environ.get("CRS_PASSWORD", "")
        self._token: str | None = None
        self._token_t = 0.0

    @property
    def live(self) -> bool:
        return bool(self.email and self.password)

    def _login(self) -> str | None:
        if not self.live:
            return None
        if self._token and time.time() - self._token_t < 600:
            return self._token
        r = httpx.post(f"{BASE}/users/login",
                       json={"email": self.email, "password": self.password},
                       timeout=15)
        r.raise_for_status()
        data = r.json()
        self._token = data.get("token") or data.get("access_token")
        self._token_t = time.time()
        return self._token

    def _get(self, path: str) -> dict:
        tok = self._login()
        r = httpx.get(f"{BASE}{path}",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict) -> dict:
        tok = self._login()
        r = httpx.post(f"{BASE}{path}", json=body,
                       headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        r.raise_for_status()
        return r.json()

    # ---- product calls (mock fallback keeps the demo alive) ----

    def verify_identity(self, first_name: str, last_name: str,
                        ssn: str) -> dict:
        """IDV: does this identity check out with the bureaus?"""
        if self.live:
            try:
                data = self._post("/idv/verify", {
                    "first_name": first_name, "last_name": last_name,
                    "ssn": ssn,
                })
                return {"mode": "live", "verified": bool(
                    data.get("verified", data.get("passed", True))),
                    "raw": data}
            except Exception as e:
                return {"mode": "live-error", "verified": False,
                        "error": str(e)[:200]}
        # mock: the known CRS test identity verifies; anything else fails
        ok = (first_name.upper() == TEST_IDENTITY["first_name"]
              and last_name.upper() == TEST_IDENTITY["last_name"]
              and ssn.replace("-", "") == TEST_IDENTITY["ssn"])
        return {"mode": "mock", "verified": ok}

    def ofac_screen(self, first_name: str, last_name: str) -> dict:
        """Compliance: OFAC watchlist screen (used at device registration)."""
        if self.live:
            try:
                data = self._post("/compliance/ofac", {
                    "first_name": first_name, "last_name": last_name})
                return {"mode": "live",
                        "clear": not data.get("match", False), "raw": data}
            except Exception as e:
                return {"mode": "live-error", "clear": True,
                        "error": str(e)[:200]}
        return {"mode": "mock", "clear": True}


_client: CRSClient | None = None


def get_client() -> CRSClient:
    global _client
    if _client is None:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except Exception:
            pass
        _client = CRSClient()
    return _client
