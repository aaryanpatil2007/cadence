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

BASE = "https://api.nessieisreal.com"
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
            "rewards": 0, "balance": 18500})["objectCreated"]["_id"]
        self.savings_id = self._req("POST", f"/customers/{cid}/accounts", {
            "type": "Savings", "nickname": "gait-savings",
            "rewards": 0, "balance": 42200})["objectCreated"]["_id"]
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({
            "customer_id": cid,
            "checking_id": self.checking_id,
            "savings_id": self.savings_id,
        }))
        print(f"[nessie] created customer {cid[:8]}… with checking + savings")

    def _transfer_total(self) -> float:
        try:
            rows = self._req("GET", f"/accounts/{self.checking_id}/transfers")
            return sum(float(r.get("amount", 0)) for r in rows
                       if r.get("status") == "completed")
        except Exception:
            return 0.0

    def balances(self) -> list[dict] | None:
        """The sandbox never mutates stored balances, so compute them from
        Nessie's own data: opening balance +/- the live transfer ledger."""
        chk = self._get_account(self.checking_id)
        sav = self._get_account(self.savings_id)
        if chk is None or sav is None:
            return None
        moved = self._transfer_total()
        return [{"name": "checking", "balance": float(chk["balance"]) - moved},
                {"name": "savings", "balance": float(sav["balance"]) + moved}]

    def ledger(self, limit: int = 30) -> list[dict]:
        """Recent transfers from Nessie's own ledger, newest first, in the
        bank UI's activity shape."""
        try:
            rows = self._req("GET", f"/accounts/{self.checking_id}/transfers")
        except Exception:
            return []
        out = []
        for r in rows:
            if r.get("status") != "completed":
                continue
            desc = (r.get("description") or "transfer").strip()
            if ":" in desc:  # e.g. "to savings: november rent"
                desc = desc.split(":", 1)[1].strip() or desc
            out.append({"ts": None, "frm": "checking",
                        "to": desc,
                        "amount": float(r.get("amount", 0)),
                        "memo": f"Agent payment · {desc}",
                        "decision": "allow", "score": None,
                        "reason": "agent payment · Capital One Nessie",
                        "date": r.get("transaction_date")})
        return list(reversed(out))[:limit]

    def transfer(self, amount: float, memo: str) -> dict:
        """Create a Nessie transfer record (the calhacks sandbox's
        TransferCreate takes only {transaction_date, status, amount,
        description}); balances shown in the UI are derived from this ledger
        in balances()."""
        import datetime
        return self._req("POST", f"/accounts/{self.checking_id}/transfers", {
            "transaction_date": datetime.date.today().isoformat(),
            "status": "completed",
            "amount": amount,
            "description": f"to savings: {(memo or 'gait transfer')[:200]}",
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
