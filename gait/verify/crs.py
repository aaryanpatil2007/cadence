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

# Sandbox persona P01 (prime; IDV PASS; FICO 790; fraud risk 11) — anchor
PASS_PERSONA = {
    "firstName": "MARGARET", "lastName": "OKAFOR", "ssn": "666701001",
    "dob": "1984-03-14", "street1": "1420 WILLOW CREEK DR",
    "city": "SAN JOSE", "state": "CA", "zip": "95125",
    "email": "margaret.okafor@example.com", "phone": "5550101001",
    "ip": "203.0.113.11",
}
# Sandbox persona P13 (synthetic identity; IDV FAIL; thin file; fraud risk 88)
# demo villain: email 3 days old, VOIP prepaid phone, no name match
FAIL_PERSONA = {
    "firstName": "KAYLA", "lastName": "BRENNAN", "ssn": "666701013",
    "dob": "1999-12-24", "street1": "9021 KINGSTON PIKE",
    "city": "KNOXVILLE", "state": "TN", "zip": "37923",
    "email": "kb.9921x@example.com", "phone": "5550101013",
    "ip": "198.51.100.13",
}

IDV_FIELDS = ["firstName", "lastName", "ssn", "dob",
              "street1", "city", "state", "zip"]

CREDIT_CONFIG = "tu-prequal-fico9"
FRAUD_CONFIG = "fraud-finder"
# persona-accurate mock outcomes (keyed by ssn)
_MOCK_CREDIT = {"666701001": 790, "666701005": 540, "666701013": 640}
_MOCK_FRAUD = {"666701001": 11, "666701005": 52, "666701013": 88}


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


    def credit_score(self, persona: dict) -> dict:
        """TransUnion FICO 9 soft-pull. Returns {mode, score, band}."""
        if self.live:
            try:
                tok = self._login()
                body = {
                    "firstName": persona["firstName"], "lastName": persona["lastName"],
                    "ssn": persona["ssn"].replace("-", ""),
                    "addresses": [{"addressLine1": persona["street1"],
                                   "city": persona["city"], "state": persona["state"],
                                   "postalCode": persona["zip"],
                                   "borrowerResidencyType": "Current"}],
                }
                r = httpx.post(
                    f"{BASE}/transunion/credit-report/standard/{CREDIT_CONFIG}",
                    json=body, headers={"Authorization": f"Bearer {tok}",
                                        "Content-Type": "application/json"},
                    timeout=40)
                r.raise_for_status()
                data = r.json()
                score = None
                for rpt in (data.get("creditReports") or [data]):
                    for s in (rpt.get("scores") or []):
                        if s.get("scoreValue") is not None:
                            score = int(s["scoreValue"])
                            break
                    if score:
                        break
                return {"mode": "live", "score": score, "band": _band(score)}
            except Exception as e:
                return {"mode": "live-error", "score": None, "band": "unknown",
                        "error": str(e)[:160]}
        score = _MOCK_CREDIT.get(persona["ssn"].replace("-", ""))
        return {"mode": "mock", "score": score, "band": _band(score)}

    def fraud_score(self, persona: dict) -> dict:
        """AtData Fraud Finder: email/phone/IP fraud risk. Returns
        {mode, risk, level, signals}."""
        if self.live:
            try:
                tok = self._login()
                body = {
                    "firstName": persona["firstName"], "lastName": persona["lastName"],
                    "email": persona.get("email", ""),
                    "phoneNumber": persona.get("phone", ""),
                    "ipAddress": persona.get("ip", ""),
                    "address": {"addressLine1": persona["street1"],
                                "city": persona["city"], "state": persona["state"],
                                "postalCode": persona["zip"]},
                }
                r = httpx.post(f"{BASE}/fraud-finder/{FRAUD_CONFIG}", json=body,
                               headers={"Authorization": f"Bearer {tok}",
                                        "Content-Type": "application/json"},
                               timeout=40)
                r.raise_for_status()
                data = r.json()
                risk = (data.get("risk") or {}).get("score")
                return {"mode": "live", "risk": risk, "level": _fraud_level(risk),
                        "signals": _fraud_signals(data)}
            except Exception as e:
                return {"mode": "live-error", "risk": None, "level": "unknown",
                        "signals": [], "error": str(e)[:160]}
        risk = _MOCK_FRAUD.get(persona["ssn"].replace("-", ""))
        sig = (["email 3 days old", "VOIP prepaid phone", "name/email mismatch"]
               if risk and risk >= 70 else [])
        return {"mode": "mock", "risk": risk, "level": _fraud_level(risk),
                "signals": sig}


def _band(score: int | None) -> str:
    if score is None:
        return "no-file"
    if score >= 740:
        return "prime"
    if score >= 670:
        return "near-prime"
    if score >= 580:
        return "subprime"
    return "deep-subprime"


def _fraud_level(risk: int | None) -> str:
    if risk is None:
        return "unknown"
    if risk >= 70:
        return "high"
    if risk >= 40:
        return "medium"
    return "low"


def _fraud_signals(data: dict) -> list[str]:
    out = []
    email = data.get("email") or {}
    if isinstance(email, dict):
        age = email.get("firstSeenDays") or email.get("ageDays")
        if isinstance(age, (int, float)) and age < 30:
            out.append(f"email only {int(age)} days old")
    phone = data.get("phone") or {}
    if isinstance(phone, dict):
        if str(phone.get("lineType", "")).lower() in ("voip", "prepaid"):
            out.append(f"{phone['lineType']} phone")
        if str(phone.get("ownerMatch", "")).lower() in ("no_match", "none"):
            out.append("phone owner mismatch")
    return out


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
