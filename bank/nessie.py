"""Capital One Nessie backend (optional; mock ledger is the fallback)."""
from __future__ import annotations

import httpx

BASE = "http://api.nessieisreal.com"


class Nessie:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("no NESSIE_API_KEY")
        self.key = api_key
        self.checking_id: str | None = None
        self.savings_id: str | None = None

    def _post(self, path: str, body: dict) -> dict:
        r = httpx.post(f"{BASE}{path}?key={self.key}", json=body, timeout=10)
        r.raise_for_status()
        return r.json()

    def boot(self) -> None:
        cust = self._post("/customers", {
            "first_name": "Gait", "last_name": "Demo",
            "address": {"street_number": "1", "street_name": "Main St",
                        "city": "SF", "state": "CA", "zip": "94105"},
        })["objectCreated"]
        cid = cust["_id"]
        self.checking_id = self._post(f"/customers/{cid}/accounts", {
            "type": "Checking", "nickname": "gait-checking",
            "rewards": 0, "balance": 12500})["objectCreated"]["_id"]
        self.savings_id = self._post(f"/customers/{cid}/accounts", {
            "type": "Savings", "nickname": "gait-savings",
            "rewards": 0, "balance": 48200})["objectCreated"]["_id"]

    def transfer(self, amount: float, memo: str) -> dict:
        return self._post(f"/accounts/{self.checking_id}/transfers", {
            "medium": "balance", "payee_id": self.savings_id,
            "amount": amount, "description": memo or "gait transfer"})
