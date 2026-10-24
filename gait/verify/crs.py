"""CRS sandbox client (StitchCredit): TransUnion TruValidate identity
verification — the trust ladder's top rung — plus the identity anchor at
device registration.

API (from CRS's own MCP package docs):
  POST /users/login {username, password} -> {token}
  POST /transunion/identity-manager-verification/basic {flat camelCase body}
    -> SubjectRecord; addOnProducts[0].idManagerVerification.messages[] empty
       means VERIFIED; entries like 2201/2202/2301/2401 are problems
       (SSN->other name, SSN before DOB, deceased SSN, fraud alert).

Mock mode (no CRS_USERNAME/CRS_PASSWORD) mirrors the sandbox personas so the
demo never blocks. Only CRS-provided TEST personas are ever sent.

NOTE: repeated failed logins disable the sandbox account, so a login failure
latches and live mode disables itself for the rest of the process.
"""
from __future__ import annotations

import os
import time

import httpx

BASE = os.environ.get("CRS_BASE", "https://api-sandbox.stitchcredit.com/api")

# Sandbox persona P01 (prime; IDV result: PASS) — the enrolled user's anchor
PASS_PERSONA = {
    "firstName": "MARGARET", "lastName": "OKAFOR", "ssn": "666701001",
    "dob": "1984-03-14", "street1": "1420 WILLOW CREEK DR",
    "city": "SAN JOSE", "state": "CA", "zip": "95125",
}
# Sandbox persona P13 (synthetic identity / fraud; IDV result: FAIL) — the
# demo villain: "SSN issue date inconsistent with DOB; multiple names on SSN"
FAIL_PERSONA = {
    "firstName": "KAYLA", "lastName": "BRENNAN", "ssn": "666701013",
    "dob": "1999-12-24", "street1": "9021 KINGSTON PIKE",
    "city": "KNOXVILLE", "state": "TN", "zip": "37923",
}

IDV_FIELDS = ["firstName", "lastName", "ssn", "dob",
              "street1", "city", "state", "zip"]


class CRSClient:
    def __init__(self):
        self.username = os.environ.get("CRS_USERNAME", "")
        self.password = os.environ.get("CRS_PASSWORD", "")
        self._token: str | None = None
        self._token_t = 0.0
        self._login_failed: str | None = None

    @property
    def live(self) -> bool:
        return bool(self.username and self.password) and self._login_failed is None

    def _login(self) -> str:
        if self._login_failed:
            raise RuntimeError(self._login_failed)
        if self._token and time.time() - self._token_t < 540:
            return self._token
        r = httpx.post(f"{BASE}/users/login",
                       json={"username": self.username,
                             "password": self.password}, timeout=20)
        if r.status_code != 200:
            # latch: repeated failed logins disable the sandbox account
            self._login_failed = f"CRS login failed ({r.status_code}); live mode disabled"
            raise RuntimeError(self._login_failed)
        self._token = r.json()["token"]
        self._token_t = time.time()
        return self._token

    def verify_identity(self, fields: dict) -> dict:
        """TruValidate IDV. Returns {mode, verified, messages: [{code,text}]}"""
        body = {k: str(fields.get(k, "")).strip() for k in IDV_FIELDS}
        body["ssn"] = body["ssn"].replace("-", "")
        if self.live:
            try:
                tok = self._login()
                r = httpx.post(
                    f"{BASE}/transunion/identity-manager-verification/basic",
                    json=body,
                    headers={"Authorization": f"Bearer {tok}",
                             "Content-Type": "application/json"},
                    timeout=40)
                r.raise_for_status()
                data = r.json()
                msgs = ((data.get("addOnProducts") or [{}])[0]
                        .get("idManagerVerification", {}) or {}).get("messages") or []
                return {"mode": "live", "verified": len(msgs) == 0,
                        "messages": [{"code": m.get("code"),
                                      "text": m.get("text")} for m in msgs]}
            except Exception as e:
                return {"mode": "live-error", "verified": False,
                        "messages": [{"code": "ERR", "text": str(e)[:200]}]}
        # mock: mirrors the sandbox personas
        def matches(p):
            return (body["firstName"].upper() == p["firstName"]
                    and body["lastName"].upper() == p["lastName"]
                    and body["ssn"] == p["ssn"])
        if matches(PASS_PERSONA):
            return {"mode": "mock", "verified": True, "messages": []}
        if matches(FAIL_PERSONA):
            return {"mode": "mock", "verified": False, "messages": [
                {"code": "2202", "text": "SSN issue date inconsistent with date of birth"},
                {"code": "2201", "text": "SSN has been used by multiple names"}]}
        return {"mode": "mock", "verified": False, "messages": [
            {"code": "2101", "text": "identity could not be verified"}]}


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
