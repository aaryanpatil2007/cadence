"""Authorization agent.

Reasons over the Identity Trust Graph to decide whether an action may proceed.
The *decision* is always computed deterministically from the graph policy (so
the demo can never be talked into moving money); a real Claude call narrates
the reasoning in plain English. Live runs are recorded to data/agent_runs.jsonl
and can be replayed frame-perfectly for the film (CADENCE_AGENT_REPLAY=1).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess

from gait.paths import REPO_ROOT
from .graph import IDENTITY_NODES, PRESENCE_NODES

RUNS = REPO_ROOT / "data" / "agent_runs.jsonl"


# --- deterministic policy verdict (authoritative) --------------------------
def _rule_decision(graph: dict) -> dict:
    by_id = {n["id"]: n for n in graph["nodes"]}
    cov = graph["coverage"]
    required = cov["required"]

    def state(nid):
        return by_id.get(nid, {}).get("state")

    # a present-but-wrong human, or automation -> hard deny
    bad_presence = [n for n in PRESENCE_NODES if state(n) == "contradicted"]
    if bad_presence:
        return {"decision": "deny", "missing": bad_presence,
                "challenge": "Re-authenticate — the person present is not the mandate holder."}
    if state("fraud_clear") == "contradicted":
        return {"decision": "deny", "missing": ["fraud_clear"],
                "challenge": "Blocked — identity failed CRS fraud screening."}

    missing = [n for n in required if state(n) != "lit"]
    if not missing:
        return {"decision": "allow", "missing": [], "challenge": ""}
    if any(n in IDENTITY_NODES for n in missing):
        return {"decision": "step_up", "missing": missing,
                "challenge": "Verify identity with CRS (TruValidate) before this amount clears."}
    return {"decision": "step_up", "missing": missing,
            "challenge": "Additional verification needed to cover this action."}


# --- scenario key (for record/replay) --------------------------------------
def _scenario_key(action: dict, graph: dict) -> str:
    by_id = {n["id"]: n for n in graph["nodes"]}
    amount = float(action.get("amount", 0) or 0)
    band = "lo" if amount <= 500 else "mid" if amount <= 2500 else "hi"
    rec = by_id.get("recipient_known", {}).get("state", "na")
    cont = by_id.get("continuity", {}).get("state", "na")
    ident = "".join(by_id.get(n, {}).get("state", "n")[0] for n in IDENTITY_NODES)
    raw = f"{band}|{rec}|{cont}|{ident}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# --- Claude narration -------------------------------------------------------
def _prompt(action: dict, graph: dict, verdict: dict) -> str:
    by_id = {n["id"]: n for n in graph["nodes"]}
    lines = []
    for tier in ("identity", "device", "presence", "money"):
        for n in graph["nodes"]:
            if n["tier"] == tier:
                lines.append(f"  [{n['state']:>12}] {n['label']} ({n['source']}): {n['detail']}")
    m = graph["mandate"]
    return (
        "You are Cadence, the authorization agent for a bank. An AI payment agent "
        "wants to move money on a human's behalf. You decide whether a REAL, authorized "
        "human is provably present and consenting, by reasoning over a live identity "
        "trust graph. You do not move money unless the policy is satisfied.\n\n"
        f"ACTION: pay {action.get('recipient','?')} ${float(action.get('amount',0) or 0):,.0f}"
        f" (memo: {action.get('memo','')})\n"
        f"MANDATE: root={m['root']} · scope={m['scope']} · autonomous ceiling=${m['max_amount']:,}"
        f" · active={m['active']}\n"
        "POLICY: amounts above the autonomous ceiling are PERMITTED when the full "
        "identity tier is lit (bureau-verified step-up via CRS) — the ceiling bounds "
        "unattended spending, not identity-verified actions.\n\n"
        "TRUST GRAPH (node state in brackets — lit=fresh evidence, stale=missing, "
        "contradicted=evidence against):\n" + "\n".join(lines) + "\n\n"
        f"POLICY ENGINE VERDICT (authoritative, do not override): {verdict['decision']}"
        + (f" — {verdict['challenge']}" if verdict['challenge'] else "") + "\n\n"
        "Explain this verdict as the agent, reasoning over the graph. Reply with ONLY a "
        "JSON object, no prose, no markdown fence:\n"
        '{"reasoning": ["3-5 short first-person steps a judge can follow"], '
        '"explanation": "one plain-English sentence stating the decision and why"}'
    )


def _extract_json(text: str) -> dict | None:
    text = (text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
        return obj if isinstance(obj, dict) and "reasoning" in obj else None
    except Exception:
        return None


def _run_claude(prompt: str, tries: int = 2) -> dict | None:
    for _ in range(tries):
        try:
            r = subprocess.run(
                ["claude", "-p", prompt, "--model", "haiku",
                 "--output-format", "json"],
                capture_output=True, text=True, timeout=90)
            if r.returncode == 0 and r.stdout.strip():
                try:
                    inner = json.loads(r.stdout).get("result", "")
                except Exception:
                    inner = r.stdout
                obj = _extract_json(inner)
                if obj:
                    return obj
        except Exception:
            pass
    return None


def _deterministic_narration(action: dict, graph: dict, verdict: dict) -> dict:
    by_id = {n["id"]: n for n in graph["nodes"]}
    amt = f"${float(action.get('amount', 0) or 0):,.0f}"
    steps = [f"Action: pay {action.get('recipient','?')} {amt}."]
    cont = by_id.get("continuity", {})
    if verdict["decision"] == "allow":
        steps += [
            f"Presence is live — {cont.get('detail','continuous')}.",
            "Identity confirmed by CRS; device key and recipient history check out.",
            "Required evidence is fully lit → within the human-rooted mandate.",
        ]
        expl = f"Approved — a verified, present human authorized this {amt} payment."
    elif verdict["decision"] == "deny" and by_id.get("fraud_clear", {}).get("state") == "contradicted":
        steps += ["CRS Fraud Finder flags this identity as high-risk / synthetic.",
                  "The identity tier is contradicted — the graph cannot support this.",
                  "Holding the money and rejecting the authorization."]
        expl = "Blocked — CRS flagged a synthetic identity; no money moves."
    elif verdict["decision"] == "deny":
        steps += [f"Presence broke — {cont.get('detail','the typist changed')}.",
                  "The mandate is rooted in a specific human who is no longer present.",
                  "Freezing the pending transfer and revoking the agent's authority."]
        expl = "Blocked — the person at the keyboard is no longer the mandate holder; money frozen."
    else:
        miss = ", ".join(verdict["missing"])
        steps += [f"Coverage short — missing: {miss}.",
                  "This amount exceeds the standing mandate; I need fresh proof.",
                  verdict["challenge"]]
        expl = f"Step-up required — {verdict['challenge']}"
    return {"reasoning": steps, "explanation": expl}


# --- public -----------------------------------------------------------------
def authorize(action: dict, graph: dict) -> dict:
    verdict = _rule_decision(graph)
    key = _scenario_key(action, graph)

    if os.environ.get("CADENCE_AGENT_REPLAY") == "1" and RUNS.exists():
        for line in reversed(RUNS.read_text().splitlines()):
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("key") == key:
                out = rec["output"]
                out["agent"] = "claude·recorded"
                return out

    narration = _run_claude(_prompt(action, graph, verdict))
    agent = "claude"
    if not narration or "reasoning" not in narration:
        narration = _deterministic_narration(action, graph, verdict)
        agent = "policy-engine"

    out = {
        "decision": verdict["decision"],
        "reasoning": [str(s) for s in narration.get("reasoning", [])][:6],
        "explanation": str(narration.get("explanation", "")),
        "missing": verdict["missing"],
        "challenge": verdict["challenge"],
        "agent": agent,
    }

    if agent == "claude":
        try:
            RUNS.parent.mkdir(parents=True, exist_ok=True)
            with RUNS.open("a") as f:
                f.write(json.dumps({"key": key, "action": action,
                                    "output": out}) + "\n")
        except Exception:
            pass
    return out
