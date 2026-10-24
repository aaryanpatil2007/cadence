import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowRight, Check, Loader2, ScanFace, ShieldCheck } from "lucide-react";

const SPRING = { type: "spring", stiffness: 300, damping: 32 } as const;
const BANK = `http://${location.hostname || "127.0.0.1"}:7900`;
const VERIFIER = `http://${location.hostname || "127.0.0.1"}:7800`;
const DAEMON = "http://127.0.0.1:7777";

type Decision = "allow" | "stepup" | "deny";
type Factor = { dimension: string; label: string; detail: string; severity: string };
type Transfer = { ts: number; to: string; amount: number; memo: string; decision: Decision; score: number | null };

// Ada jewel accent per signal dimension (left-edge bars)
const DIM_ACCENT: Record<string, string> = {
  Presence: "var(--forest)", Identity: "var(--periwinkle)",
  Device: "var(--candy)", Transaction: "var(--butter)",
};
const DIMS = ["Presence", "Identity", "Device", "Transaction"] as const;
const DIM_BLURB: Record<string, string> = {
  Presence: "Is the enrolled human here?",
  Identity: "Real, non-synthetic person?",
  Device: "Trusted device and network?",
  Transaction: "Normal for this account?",
};

const decColor = (d: string | null) => d === "allow" ? "var(--forest)" : d === "stepup" ? "var(--amber-ink)" : d === "deny" ? "var(--crimson)" : "var(--muted)";
const sevColor = (s: string) => s === "ok" ? "var(--forest)" : s === "warn" ? "var(--amber-ink)" : "var(--crimson)";

function deviceFingerprint(): string {
  try {
    const c = document.createElement("canvas");
    const ctx = c.getContext("2d");
    if (ctx) { ctx.textBaseline = "top"; ctx.font = "14px Arial"; ctx.fillStyle = "#f60"; ctx.fillRect(0, 0, 60, 20); ctx.fillStyle = "#069"; ctx.fillText("cadence", 2, 2); }
    const bits = [c.toDataURL(), navigator.userAgent, navigator.language, `${screen.width}x${screen.height}`, new Date().getTimezoneOffset(), navigator.hardwareConcurrency].join("|");
    let h = 0; for (let i = 0; i < bits.length; i++) { h = (h << 5) - h + bits.charCodeAt(i); h |= 0; }
    return "fp" + Math.abs(h).toString(36);
  } catch { return "fp-x"; }
}

export default function App() {
  const [loggedIn, setLoggedIn] = useState(false);
  const [backend, setBackend] = useState("mock");
  const [accounts, setAccounts] = useState<{ name: string; balance: number }[]>([]);
  const [amount, setAmount] = useState("500");
  const [memo, setMemo] = useState("");
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<"nonce" | "attest" | "sign" | "risk" | "">("");
  const [decision, setDecision] = useState<Decision | null>(null);
  const [reason, setReason] = useState("");
  const [factors, setFactors] = useState<Factor[]>([]);
  const [trust, setTrust] = useState<number | null>(null);
  const [recovery, setRecovery] = useState<string[]>([]);
  const [history, setHistory] = useState<Transfer[]>([]);
  const [identity, setIdentity] = useState<{ name: string; verified: boolean; credit_score?: number; credit_band?: string } | null>(null);
  const [liveScore, setLiveScore] = useState<number | null>(null);
  const [simRisky, setSimRisky] = useState(false);
  const [challenge, setChallenge] = useState<string | null>(null);
  const [kycOpen, setKycOpen] = useState(false);
  const PASS_P = { firstName: "MARGARET", lastName: "OKAFOR", ssn: "666701001", dob: "1984-03-14", street1: "1420 WILLOW CREEK DR", city: "SAN JOSE", state: "CA", zip: "95125" };
  const SYNTH_P = { firstName: "KAYLA", lastName: "BRENNAN", ssn: "666701013", dob: "1999-12-24", street1: "9021 KINGSTON PIKE", city: "KNOXVILLE", state: "TN", zip: "37923" };
  const [kyc, setKyc] = useState<Record<string, string>>(PASS_P);
  const [kycState, setKycState] = useState<"idle" | "checking" | "failed">("idle");
  const [kycMsg, setKycMsg] = useState("");
  const [touchState, setTouchState] = useState<"idle" | "waiting" | "failed">("idle");
  const histRef = useRef<Transfer[]>([]);

  const refresh = useCallback(() => {
    fetch(`${BANK}/accounts`, { credentials: "include" }).then((r) => r.ok ? r.json() : Promise.reject())
      .then((j) => { setAccounts(j.accounts); setBackend(j.backend ?? "mock"); setLoggedIn(true); }).catch(() => {});
    fetch(`${BANK}/transfers`).then((r) => r.json()).then((j) => { setHistory(j.transfers); histRef.current = j.transfers; }).catch(() => {});
    fetch(`${DAEMON}/status`).then((r) => r.json()).then((s) => fetch(`${VERIFIER}/identity/${s.device_id}`)).then((r) => r.json()).then((j) => setIdentity(j.identity ?? null)).catch(() => {});
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    const es = new EventSource(`${DAEMON}/events`);
    es.addEventListener("score", (e) => { try { setLiveScore(JSON.parse((e as MessageEvent).data).score); } catch { /* */ } });
    return () => es.close();
  }, []);

  const login = async () => { await fetch(`${BANK}/login`, { method: "POST", credentials: "include" }); refresh(); };
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  const runTransfer = async () => {
    setBusy(true); setDecision(null); setChallenge(null); setKycOpen(false); setTouchState("idle"); setFactors([]);
    try {
      setPhase("nonce");
      const { nonce } = await (await fetch(`${VERIFIER}/nonce`)).json();
      await sleep(280); setPhase("attest");
      const ar = await fetch(`${DAEMON}/attest?nonce=${encodeURIComponent(nonce)}`);
      if (!ar.ok) { setPhase(""); setDecision("deny"); setReason("No behavioral signal yet — type in the memo so Cadence can sense you."); setRecovery([]); return; }
      const att = await ar.json();
      await sleep(280); setPhase("sign"); await sleep(280); setPhase("risk");
      const res = await (await fetch(`${BANK}/transfer`, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ to: "savings", amount: parseFloat(amount) || 0, memo, jws: att.jws, fingerprint: deviceFingerprint(), client_ip: simRisky ? "52.14.88.3" : "", user_agent: navigator.userAgent, history: histRef.current.filter((h) => h.decision === "allow").map((h) => ({ amount: h.amount, to: h.to, ts: h.ts })) }),
      })).json();
      await sleep(420);
      const d = (res.decision as Decision) ?? "deny";
      setFactors(res.factors ?? []); setTrust(res.trust ?? null); setDecision(d); setReason(res.reason ?? ""); setRecovery(res.recovery ?? []); setPhase("");
      if (res.identity) setIdentity(res.identity);
      if (d === "stepup" && (res.recovery ?? []).includes("challenge")) {
        const sj = await (await fetch(`${DAEMON}/stepup/start`, { method: "POST" })).json(); setChallenge(sj.challenge);
      } else if (d === "stepup" && res.kyc_required) {
        setKycOpen(true);   // high-value: surface the CRS bureau step directly
      }
      refresh();
    } finally { setBusy(false); }
  };

  const finishChallenge = async () => {
    await fetch(`${DAEMON}/stepup/finish`, { method: "POST" });
    try { const st = await (await fetch(`${DAEMON}/status`)).json(); await fetch(`${VERIFIER}/challenge`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ device_id: st.device_id }) }); } catch { /* */ }
    setChallenge(null); await runTransfer();
  };
  const touchId = async () => {
    setTouchState("waiting");
    try { const j = await (await fetch(`${DAEMON}/touchid`, { method: "POST" })).json(); if (j.ok) { setTouchState("idle"); await runTransfer(); } else setTouchState("failed"); } catch { setTouchState("failed"); }
  };
  const submitKyc = async () => {
    setKycState("checking");
    try {
      const st = await (await fetch(`${DAEMON}/status`)).json();
      const j = await (await fetch(`${VERIFIER}/kyc`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ device_id: st.device_id, ...kyc }) })).json();
      if (j.verified) { setKycOpen(false); setKycState("idle"); setKycMsg(""); await runTransfer(); }
      else { setKycState("failed"); setKycMsg((j.messages ?? []).map((m: { text: string }) => m.text).join(" · ") || "Identity could not be verified."); }
    } catch { setKycState("failed"); setKycMsg("Verification service unreachable."); }
  };

  if (!loggedIn) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center px-6" style={{ background: "var(--bone)" }}>
        <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={SPRING} className="text-center" style={{ maxWidth: 560 }}>
          <div className="label mb-7" style={{ letterSpacing: "0.12em" }}>Meridian · private banking</div>
          <h1 className="display" style={{ fontSize: 58, lineHeight: 1.05 }}>Money that knows<br />it's really you.</h1>
          <p style={{ fontSize: 19, color: "var(--muted)", marginTop: 20, lineHeight: 1.5 }}>
            No password to steal, no code to intercept. Meridian verifies every transfer by how you behave — continuously, invisibly.</p>
          <button onClick={login} className="pill mt-9" style={{ padding: "13px 34px", fontSize: 16 }}>Enter</button>
        </motion.div>
      </div>
    );
  }

  const checking = accounts.find((a) => a.name === "checking")?.balance ?? 0;
  const savings = accounts.find((a) => a.name === "savings")?.balance ?? 0;
  const presencePct = liveScore == null ? null : Math.round(liveScore * 100);

  return (
    <div className="min-h-screen" style={{ background: "var(--bone)" }}>
      {/* nav */}
      <header className="flex items-center justify-between px-9" style={{ height: 66, borderBottom: "1px solid var(--line)", background: "var(--paper)" }}>
        <div className="flex items-center gap-4">
          <span className="display" style={{ fontSize: 20, letterSpacing: "-0.02em" }}>Meridian</span>
          <div className="flex items-center gap-2">
            {backend === "nessie" && <Chip dot="var(--forest)" text="Capital One · live" />}
            {identity?.verified && <Chip dot="var(--periwinkle)" text={`${identity.name}${identity.credit_score ? ` · ${identity.credit_score} ${identity.credit_band}` : ""} · CRS`} />}
          </div>
        </div>
        <PresencePill pct={presencePct} />
      </header>

      <main className="mx-auto px-9 py-9" style={{ maxWidth: 1180 }}>
        {/* balances */}
        <div className="grid grid-cols-2 gap-5 mb-8" style={{ maxWidth: 620 }}>
          <Balance name="Checking" value={checking} />
          <Balance name="Savings" value={savings} />
        </div>

        <div className="grid gap-5" style={{ gridTemplateColumns: "minmax(0,400px) 1fr" }}>
          {/* composer */}
          <section className="card" style={{ padding: 28 }}>
            <div className="label mb-5">Send money</div>
            <div className="flex flex-col gap-3">
              <Row label="From" value="Checking" />
              <Row label="To" value="Savings" />
              <div className="field" style={{ padding: "11px 16px" }}>
                <div className="label" style={{ fontSize: 10.5, marginBottom: 3 }}>Amount</div>
                <div className="flex items-center gap-1.5">
                  <span className="display" style={{ fontSize: 26, color: "var(--muted)" }}>$</span>
                  <input className="display" style={{ fontSize: 26 }} value={amount} inputMode="decimal" onChange={(e) => setAmount(e.target.value)} />
                </div>
              </div>
              <div className="field" style={{ padding: "11px 16px" }}>
                <div className="label" style={{ fontSize: 10.5, marginBottom: 3 }}>Memo</div>
                <input value={memo} placeholder="what's this for? (type naturally)" onChange={(e) => setMemo(e.target.value)} style={{ fontSize: 16 }} />
              </div>
            </div>
            <label className="flex items-center gap-2.5 mt-5 cursor-pointer select-none" style={{ color: "var(--muted)", fontSize: 13 }}>
              <input type="checkbox" checked={simRisky} onChange={(e) => setSimRisky(e.target.checked)} style={{ accentColor: "var(--ink)", width: 15, height: 15 }} />
              Demo: simulate a VPN / datacenter network
            </label>
            <button onClick={runTransfer} disabled={busy} className="pill w-full mt-5 flex items-center justify-center gap-2" style={{ padding: 14, fontSize: 16 }}>
              {busy ? <><Loader2 size={17} className="animate-spin" /> Verifying…</> : <>Send ${amount || "0"} <ArrowRight size={16} /></>}
            </button>
            <AnimatePresence>
              {decision === "stepup" && !challenge && !kycOpen && <Recovery recovery={recovery} onTouch={touchId} touchState={touchState} onKyc={() => setKycOpen(true)} />}
              {decision === "deny" && <Recovery recovery={recovery} onTouch={touchId} touchState={touchState} onKyc={() => setKycOpen(true)} denied />}
              {challenge && <ChallengeBox sentence={challenge} onDone={finishChallenge} />}
              {kycOpen && <KycBox kyc={kyc} setKyc={setKyc} state={kycState} msg={kycMsg} onSubmit={submitKyc} onSynthetic={() => { setKyc(SYNTH_P); setKycState("idle"); }} onReset={() => { setKyc(PASS_P); setKycState("idle"); }} />}
            </AnimatePresence>
          </section>

          {/* decision + signals */}
          <section className="flex flex-col gap-5">
            <Decision phase={phase} decision={decision} reason={reason} trust={trust} />
            <div className="grid grid-cols-2 gap-5">
              {DIMS.map((dim) => <SignalCard key={dim} dim={dim} factors={factors.filter((f) => f.dimension === dim)} active={!!decision} />)}
            </div>
          </section>
        </div>

        {history.length > 0 && (
          <section className="card mt-8" style={{ padding: 26 }}>
            <div className="label mb-4">Recent activity</div>
            {history.slice(0, 6).map((t, i) => (
              <div key={i} className="flex items-center justify-between" style={{ padding: "11px 0", borderTop: i ? "1px solid var(--line)" : "none" }}>
                <div className="flex items-center gap-3">
                  <span style={{ width: 3, height: 26, borderRadius: 2, background: decColor(t.decision) }} />
                  <span style={{ fontSize: 15 }}>{t.memo || "Transfer to Savings"}</span>
                </div>
                <div className="flex items-center gap-7">
                  <span className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>{t.score != null ? `${Math.round(t.score * 100)}% trust` : "—"}</span>
                  <span className="mono" style={{ fontSize: 15, width: 96, textAlign: "right" }}>${t.amount.toFixed(2)}</span>
                  <span className="label" style={{ width: 54, textAlign: "right", color: decColor(t.decision) }}>{t.decision}</span>
                </div>
              </div>
            ))}
          </section>
        )}
      </main>
    </div>
  );
}

function Chip({ dot, text }: { dot: string; text: string }) {
  return (
    <span className="flex items-center gap-1.5 px-2.5 py-1" style={{ borderRadius: 9999, fontSize: 12, color: "var(--muted)", border: "1px solid var(--line)" }}>
      <span style={{ width: 6, height: 6, borderRadius: 9999, background: dot }} />{text}
    </span>
  );
}

function PresencePill({ pct }: { pct: number | null }) {
  const c = pct == null ? "var(--muted)" : pct >= 70 ? "var(--forest)" : pct >= 40 ? "var(--amber-ink)" : "var(--crimson)";
  const word = pct == null ? "Sensing…" : pct >= 70 ? "You're present" : pct >= 40 ? "Uncertain" : "Not recognized";
  return (
    <div className="flex items-center gap-2.5 px-3.5 py-1.5" style={{ borderRadius: 9999, border: "1px solid var(--line)" }}>
      <span style={{ width: 6, height: 6, borderRadius: 9999, background: c }} />
      <span style={{ fontSize: 13, color: "var(--muted)" }}>{word}</span>
      <span className="mono" style={{ fontSize: 13, color: c }}>{pct == null ? "—" : `${pct}%`}</span>
    </div>
  );
}

function Balance({ name, value }: { name: string; value: number }) {
  return (
    <div className="card" style={{ padding: 22 }}>
      <div className="label mb-2">{name}</div>
      <div className="display tnum" style={{ fontSize: 32 }}>${value.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="field flex items-center justify-between" style={{ padding: "11px 16px" }}>
      <span className="label" style={{ fontSize: 10.5 }}>{label}</span>
      <span style={{ fontSize: 16 }}>{value}</span>
    </div>
  );
}

const PHASE_STEPS = [
  { key: "nonce", label: "Requesting a one-time challenge" },
  { key: "attest", label: "Reading your behavioral signature" },
  { key: "sign", label: "Signing in the Secure Enclave" },
  { key: "risk", label: "Scoring four fraud signals" },
] as const;

function Decision({ phase, decision, reason, trust }: { phase: string; decision: Decision | null; reason: string; trust: number | null }) {
  const col = decColor(decision);
  const title = decision === "allow" ? "Transfer approved" : decision === "stepup" ? "One more check" : decision === "deny" ? "Transfer blocked" : "Ready when you are";
  return (
    <div className="card" style={{ padding: 28 }}>
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0" style={{ paddingRight: 16 }}>
          <AnimatePresence mode="wait">
            <motion.div key={(decision ?? "") + phase} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={SPRING}>
              <div className="display" style={{ fontSize: 26, color: decision ? col : "var(--ink)" }}>{phase ? "Verifying…" : title}</div>
              <p style={{ color: "var(--muted)", fontSize: 15, marginTop: 5, lineHeight: 1.45 }}>
                {phase ? PHASE_STEPS.find((s) => s.key === phase)?.label : decision ? reason : "Compose a transfer and Cadence scores it across four signals."}
              </p>
            </motion.div>
          </AnimatePresence>
        </div>
        {decision && trust != null && (
          <div className="text-right shrink-0">
            <div className="label" style={{ marginBottom: 3 }}>Trust</div>
            <div className="display tnum" style={{ fontSize: 34, color: col }}>{Math.round(trust * 100)}</div>
          </div>
        )}
      </div>
      {phase && (
        <div className="mt-6 flex flex-col gap-2.5">
          {PHASE_STEPS.map((s) => {
            const idx = PHASE_STEPS.findIndex((x) => x.key === phase), si = PHASE_STEPS.findIndex((x) => x.key === s.key);
            const done = si < idx, active = si === idx;
            return (
              <div key={s.key} className="flex items-center gap-3" style={{ opacity: done || active ? 1 : 0.32 }}>
                {done ? <Check size={15} color="var(--forest)" /> : active ? <Loader2 size={15} className="animate-spin" color="var(--ink)" /> : <span style={{ width: 15 }} />}
                <span style={{ fontSize: 14, color: active ? "var(--ink)" : "var(--muted)" }}>{s.label}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function SignalCard({ dim, factors, active }: { dim: string; factors: Factor[]; active: boolean }) {
  const accent = DIM_ACCENT[dim];
  return (
    <div className="card relative overflow-hidden" style={{ padding: "20px 20px 20px 22px", opacity: active ? 1 : 0.55 }}>
      <span style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 4, background: accent }} />
      <div className="flex items-center justify-between mb-2.5">
        <span style={{ fontSize: 15, fontWeight: 500 }}>{dim}</span>
        {active && factors.length > 0 && (
          <span style={{ width: 7, height: 7, borderRadius: 9999, background: factors.some((f) => f.severity === "bad") ? "var(--crimson)" : factors.some((f) => f.severity === "warn") ? "var(--amber-ink)" : "var(--forest)" }} />
        )}
      </div>
      {!active || factors.length === 0 ? (
        <p style={{ fontSize: 13, color: "var(--muted)" }}>{DIM_BLURB[dim]}</p>
      ) : (
        <div className="flex flex-col gap-2">
          {factors.map((f, i) => (
            <div key={i}>
              <div style={{ fontSize: 13.5, color: sevColor(f.severity) }}>{f.label}</div>
              <div style={{ fontSize: 12.5, color: "var(--muted)", lineHeight: 1.4 }}>{f.detail}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Recovery({ recovery, onTouch, touchState, onKyc, denied }: { recovery: string[]; onTouch: () => void; touchState: string; onKyc: () => void; denied?: boolean }) {
  return (
    <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
      <div className="mt-5" style={{ paddingTop: 18, borderTop: "1px solid var(--line)" }}>
        <p style={{ fontSize: 14, color: "var(--muted)", marginBottom: 12 }}>
          {denied ? "This doesn't look like the account owner. If it's really you:" : "Cadence isn't fully sure — one quick confirmation:"}
        </p>
        <div className="flex flex-col gap-2.5">
          {recovery.includes("touchid") && (
            <button onClick={onTouch} disabled={touchState === "waiting"} className="pill-ghost flex items-center gap-3 text-left" style={{ padding: "12px 16px" }}>
              <ScanFace size={18} color="var(--ink)" />
              <div className="flex-1">
                <div style={{ fontSize: 14.5 }}>{touchState === "waiting" ? "Waiting for the sensor…" : touchState === "failed" ? "Touch ID didn't match — try again" : "Confirm with Touch ID"}</div>
                <div style={{ fontSize: 12, color: "var(--muted)" }}>hardware biometric on this Mac</div>
              </div>
              <ArrowRight size={15} color="var(--muted)" />
            </button>
          )}
          {recovery.includes("kyc") && (
            <button onClick={onKyc} className="pill-ghost flex items-center gap-3 text-left" style={{ padding: "12px 16px" }}>
              <ShieldCheck size={18} color="var(--ink)" />
              <div className="flex-1">
                <div style={{ fontSize: 14.5 }}>Verify identity</div>
                <div style={{ fontSize: 12, color: "var(--muted)" }}>bureau-grade check via CRS</div>
              </div>
              <ArrowRight size={15} color="var(--muted)" />
            </button>
          )}
        </div>
      </div>
    </motion.div>
  );
}

function ChallengeBox({ sentence, onDone }: { sentence: string; onDone: () => void }) {
  const [text, setText] = useState("");
  return (
    <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
      <div className="mt-5" style={{ paddingTop: 18, borderTop: "1px solid var(--line)" }}>
        <div className="label mb-2" style={{ color: "var(--amber-ink)" }}>Type this sentence, naturally</div>
        <div style={{ fontSize: 15.5, marginBottom: 10 }}>{sentence}</div>
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} autoFocus placeholder="type here…" className="field w-full" style={{ padding: "10px 14px", fontSize: 15, resize: "none" }} />
        <button onClick={onDone} disabled={text.length < 10} className="pill mt-3" style={{ padding: "9px 20px", fontSize: 14 }}>Re-verify</button>
      </div>
    </motion.div>
  );
}

function KycBox({ kyc, setKyc, state, msg, onSubmit, onSynthetic, onReset }: { kyc: Record<string, string>; setKyc: (k: Record<string, string>) => void; state: string; msg: string; onSubmit: () => void; onSynthetic: () => void; onReset: () => void }) {
  const fields: [string, string][] = [["First name", "firstName"], ["Last name", "lastName"], ["SSN", "ssn"], ["Date of birth", "dob"], ["Street", "street1"], ["City", "city"], ["State", "state"], ["ZIP", "zip"]];
  return (
    <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
      <div className="mt-5" style={{ paddingTop: 18, borderTop: "1px solid var(--line)" }}>
        <div className="label mb-1">Identity verification · CRS</div>
        <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>High-value transfer — we confirm the account holder against the credit bureaus.</p>
        <div className="grid grid-cols-2 gap-2">
          {fields.map(([label, k]) => (
            <input key={k} value={kyc[k]} placeholder={label} onChange={(e) => setKyc({ ...kyc, [k]: e.target.value })} className="field" style={{ padding: "9px 12px", fontSize: 13.5 }} />
          ))}
        </div>
        {state === "failed" && <div style={{ fontSize: 12.5, color: "var(--crimson)", marginTop: 8 }}>TransUnion: {msg}</div>}
        <div className="flex items-center gap-3 mt-3 flex-wrap">
          <button onClick={onSubmit} disabled={state === "checking"} className="pill" style={{ padding: "9px 20px", fontSize: 14 }}>{state === "checking" ? "Verifying with CRS…" : "Verify identity"}</button>
          <button onClick={onSynthetic} className="label" style={{ cursor: "pointer" }}>demo: synthetic identity</button>
          <button onClick={onReset} className="label" style={{ cursor: "pointer" }}>reset</button>
        </div>
      </div>
    </motion.div>
  );
}
