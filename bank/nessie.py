"""Capital One Nessie backend (optional; mock ledger is the fallback).

Endpoints verified against the Nessie SDK / hackathon docs:
  POST /customers                      {first_name,last_name,address{...}}
  POST /customers/{id}/accounts        {type,nickname,rewards,balance}
  GET  /accounts/{id}
  POST /accounts/{id}/transfers        {medium:"balance",payee_id,amount,description}
Auth: ?key=<api key> on every call.

Created customer/account ids persist in data/nessie.json so restarts reuse
the same accounts instead of littering the sandbox.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

BASE = "http://api.nessieisreal.com"
STATE = Path(__file__).resolve().parent.parent / "data" / "nessie.json"


class Nessie:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("no NESSIE_API_KEY")
        self.key = api_key
        self.checking_id: str | None = None
        self.savings_id: str | None = None

    def _req(self, method: str, path: str, body: dict | None = None) -> dict:
        r = httpx.request(method, f"{BASE}{path}", params={"key": self.key},
                          json=body, timeout=10)
        r.raise_for_status()
        return r.json() if r.text else {}

    def _get_account(self, account_id: str) -> dict | None:
        try:
            return self._req("GET", f"/accounts/{account_id}")
        except Exception:
            return None

    def boot(self) -> None:
        # reuse previously created accounts if they still exist
        if STATE.exists():
            try:
                saved = json.loads(STATE.read_text())
                if (self._get_account(saved["checking_id"])
                        and self._get_account(saved["savings_id"])):
                    self.checking_id = saved["checking_id"]
                    self.savings_id = saved["savings_id"]
                    print(f"[nessie] reusing accounts {self.checking_id[:8]}… / "
                          f"{self.savings_id[:8]}…")
                    return
            except Exception:
                pass

        cust = self._req("POST", "/customers", {
            "first_name": "Gait", "last_name": "Demo",
            "address": {"street_number": "1", "street_name": "Main St",
                        "city": "Berkeley", "state": "CA", "zip": "94704"},
        })["objectCreated"]
        cid = cust["_id"]
        self.checking_id = self._req("POST", f"/customers/{cid}/accounts", {
            "type": "Checking", "nickname": "gait-checking",
            "rewards": 0, "balance": 12500})["objectCreated"]["_id"]
        self.savings_id = self._req("POST", f"/customers/{cid}/accounts", {
            "type": "Savings", "nickname": "gait-savings",
            "rewards": 0, "balance": 48200})["objectCreated"]["_id"]
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({
            "customer_id": cid,
            "checking_id": self.checking_id,
            "savings_id": self.savings_id,
        }))
        print(f"[nessie] created customer {cid[:8]}… with checking + savings")

    def balances(self) -> list[dict] | None:
        out = []
        for name, aid in (("checking", self.checking_id),
                          ("savings", self.savings_id)):
            acct = self._get_account(aid)
            if acct is None:
                return None
            out.append({"name": name, "balance": float(acct["balance"])})
        return out

    def transfer(self, amount: float, memo: str) -> dict:
        return self._req("POST", f"/accounts/{self.checking_id}/transfers", {
            "medium": "balance", "payee_id": self.savings_id,
            "amount": amount, "description": (memo or "gait transfer")[:255],
        })


if __name__ == "__main__":
    # smoke test: NESSIE_API_KEY=... python -m bank.nessie
    import os
    import sys
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    key = os.environ.get("NESSIE_API_KEY", "")
    if not key:
        sys.exit("set NESSIE_API_KEY in .env first")
    n = Nessie(key)
    n.boot()
    print("balances:", n.balances())
    print("transfer:", n.transfer(1.00, "nessie smoke test")["objectCreated"]["_id"])
    print("balances after:", n.balances())
    print("NESSIE OK — set USE_NESSIE=1 in .env and restart the bank")
