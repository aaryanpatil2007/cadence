import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Landmark, Fingerprint, ShieldCheck, Wifi, CreditCard, UserCheck,
  Activity, Check, ScanFace, ArrowRight, Loader2,
} from "lucide-react";

const SPRING = { type: "spring", stiffness: 300, damping: 30 } as const;
const BANK = `http://${location.hostname || "127.0.0.1"}:7900`;
const VERIFIER = `http://${location.hostname || "127.0.0.1"}:7800`;
const DAEMON = "http://127.0.0.1:7777";

type Decision = "allow" | "stepup" | "deny";
type Factor = { dimension: string; label: string; detail: string; severity: string };
type Transfer = {
  ts: number; to: string; amount: number; memo: string;
  decision: Decision; score: number | null;
};

const DIMENSIONS = [
  { key: "Presence", icon: Fingerprint, blurb: "Is the enrolled human here?" },
  { key: "Identity", icon: UserCheck, blurb: "Real, non-synthetic person?" },
  { key: "Device", icon: Wifi, blurb: "Trusted device & network?" },
  { key: "Transaction", icon: CreditCard, blurb: "Normal for this account?" },
] as const;

function sevColor(s: string) {
  return s === "ok" ? "var(--green)" : s === "warn" ? "var(--amber)" : "var(--red)";
}
function decisionColor(d: string | null) {
  return d === "allow" ? "var(--green)" : d === "stepup" ? "var(--amber)"
    : d === "deny" ? "var(--red)" : "var(--muted)";
}

function deviceFingerprint(): string {
  try {
    const c = document.createElement("canvas");
    const ctx = c.getContext("2d");
    if (ctx) {
      ctx.textBaseline = "top";
      ctx.font = "14px 'Arial'";
      ctx.fillStyle = "#f60"; ctx.fillRect(0, 0, 60, 20);
      ctx.fillStyle = "#069"; ctx.fillText("cadence", 2, 2);
    }
    const bits = [
      c.toDataURL(), navigator.userAgent, navigator.language,
      `${screen.width}x${screen.height}x${screen.colorDepth}`,
      new Date().getTimezoneOffset(), navigator.hardwareConcurrency,
    ].join("|");
    let h = 0;
    for (let i = 0; i < bits.length; i++) { h = (h << 5) - h + bits.charCodeAt(i); h |= 0; }
    return "fp" + Math.abs(h).toString(36);
  } catch { return "fp-unknown"; }
}

function TrustRing({ value, decision }: { value: number | null; decision: Decision | null }) {
  const R = 54, C = 2 * Math.PI * R;
  const v = value ?? 0;
  const col = decisionColor(decision);
  return (
    <div className="relative" style={{ width: 128, height: 128 }}>
      <svg width="128" height="128" viewBox="0 0 128 128">
        <circle cx="64" cy="64" r={R} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="7" />
        <motion.circle
          cx="64" cy="64" r={R} fill="none" stroke={col} strokeWidth="7"
          strokeLinecap="round" strokeDasharray={C}
          initial={false} animate={{ strokeDashoffset: C * (1 - v) }}
          transition={{ type: "spring", stiffness: 70, damping: 18 }}
          transform="rotate(-90 64 64)"
          style={{ filter: `drop-shadow(0 0 7px ${col}66)` }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="display" style={{ fontSize: 34, color: col }}>
          {value == null ? "—" : Math.round(v * 100)}
        </span>
        <span className="label" style={{ fontSize: 9 }}>trust</span>
      </div>
    </div>
  );
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
  const [behaviorScore, setBehaviorScore] = useState<number | null>(null);
  const [recovery, setRecovery] = useState<string[]>([]);
  const [history, setHistory] = useState<Transfer[]>([]);
  const [identity, setIdentity] = useState<{ name: string; verified: boolean;
    credit_score?: number; credit_band?: string; fraud_risk?: number } | null>(null);
  const [liveScore, setLiveScore] = useState<number | null>(null);
  const [simRisky, setSimRisky] = useState(false);

  const [challenge, setChallenge] = useState<string | null>(null);
  const [kycOpen, setKycOpen] = useState(false);
  const PASS_P = { firstName: "MARGARET", lastName: "OKAFOR", ssn: "666701001",
    dob: "1984-03-14", street1: "1420 WILLOW CREEK DR", city: "SAN JOSE", state: "CA", zip: "95125" };
  const SYNTH_P = { firstName: "KAYLA", lastName: "BRENNAN", ssn: "666701013",
    dob: "1999-12-24", street1: "9021 KINGSTON PIKE", city: "KNOXVILLE", state: "TN", zip: "37923" };
  const [kyc, setKyc] = useState<Record<string, string>>(PASS_P);
  const [kycState, setKycState] = useState<"idle" | "checking" | "failed">("idle");
  const [kycMsg, setKycMsg] = useState("");
  const [touchState, setTouchState] = useState<"idle" | "waiting" | "failed">("idle");
  const histRef = useRef<Transfer[]>([]);

  const refresh = useCallback(() => {
    fetch(`${BANK}/accounts`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((j) => { setAccounts(j.accounts); setBackend(j.backend ?? "mock"); setLoggedIn(true); })
      .catch(() => {});
    fetch(`${BANK}/transfers`).then((r) => r.json())
      .then((j) => { setHistory(j.transfers); histRef.current = j.transfers; }).catch(() => {});
    fetch(`${DAEMON}/status`).then((r) => r.json())
      .then((s) => fetch(`${VERIFIER}/identity/${s.device_id}`))
      .then((r) => r.json()).then((j) => setIdentity(j.identity ?? null)).catch(() => {});
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // live presence meter in the header (so the behavioral layer is visible, not the whole show)
  useEffect(() => {
    const es = new EventSource(`${DAEMON}/events`);
    es.addEventListener("score", (e) => {
      try { setLiveScore(JSON.parse((e as MessageEvent).data).score); } catch { /* */ }
    });
    return () => es.close();
  }, []);

  const login = async () => {
    await fetch(`${BANK}/login`, { method: "POST", credentials: "include" });
    refresh();
  };

  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  const runTransfer = async () => {
    setBusy(true); setDecision(null); setChallenge(null); setKycOpen(false);
    setTouchState("idle"); setFactors([]);
    try {
      setPhase("nonce");
      const { nonce } = await (await fetch(`${VERIFIER}/nonce`)).json();
      await sleep(260);
      setPhase("attest");
      const ar = await fetch(`${DAEMON}/attest?nonce=${encodeURIComponent(nonce)}`);
      if (!ar.ok) {
        setPhase(""); setDecision("deny");
        setReason("No behavioral signal yet — type in the memo so Cadence can sense you.");
        setRecovery([]); return;
      }
      const att = await ar.json();
      setBehaviorScore(att.payload.score);
      await sleep(260);
      setPhase("sign"); await sleep(260);
      setPhase("risk");
      const res = await (await fetch(`${BANK}/transfer`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          to: "savings", amount: parseFloat(amount) || 0, memo, jws: att.jws,
          fingerprint: deviceFingerprint(),
          client_ip: simRisky ? "52.14.88.3" : "",
          user_agent: navigator.userAgent,
          history: histRef.current.filter((h) => h.decision === "allow")
            .map((h) => ({ amount: h.amount, to: h.to, ts: h.ts })),
        }),
      })).json();
      await sleep(400);

      const d = (res.decision as Decision) ?? "deny";
      setFactors(res.factors ?? []); setTrust(res.trust ?? null);
      setDecision(d); setReason(res.reason ?? ""); setRecovery(res.recovery ?? []);
      setPhase("");
      if (res.identity) setIdentity(res.identity);
      if (d === "stepup" && (res.recovery ?? []).includes("challenge")) {
        const sj = await (await fetch(`${DAEMON}/stepup/start`, { method: "POST" })).json();
        setChallenge(sj.challenge);
      }
      refresh();
    } finally { setBusy(false); }
  };

  const finishChallenge = async () => {
    await fetch(`${DAEMON}/stepup/finish`, { method: "POST" });
    try {
      const st = await (await fetch(`${DAEMON}/status`)).json();
      await fetch(`${VERIFIER}/challenge`, { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_id: st.device_id }) });
    } catch { /* */ }
    setChallenge(null); await runTransfer();
  };

  const touchId = async () => {
    setTouchState("waiting");
    try {
      const j = await (await fetch(`${DAEMON}/touchid`, { method: "POST" })).json();
      if (j.ok) { setTouchState("idle"); await runTransfer(); }
      else setTouchState("failed");
    } catch { setTouchState("failed"); }
  };

  const submitKyc = async () => {
    setKycState("checking");
    try {
      const st = await (await fetch(`${DAEMON}/status`)).json();
      const j = await (await fetch(`${VERIFIER}/kyc`, { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_id: st.device_id, ...kyc }) })).json();
      if (j.verified) { setKycOpen(false); setKycState("idle"); setKycMsg(""); await runTransfer(); }
      else {
        setKycState("failed");
        setKycMsg((j.messages ?? []).map((m: { text: string }) => m.text).join(" · ")
          || "Identity could not be verified.");
      }
    } catch { setKycState("failed"); setKycMsg("Verification service unreachable."); }
  };

  // ---------- login screen ----------
  if (!loggedIn) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center px-6"
        style={{ background: "radial-gradient(900px 600px at 50% -5%, rgba(94,158,255,0.10), transparent 60%)" }}>
        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
          transition={SPRING} className="flex flex-col items-center text-center">
          <div className="w-16 h-16 rounded-2xl flex items-center justify-center mb-6"
            style={{ background: "linear-gradient(180deg,var(--accent),var(--accent-deep))",
                     boxShadow: "0 12px 40px rgba(59,125,224,0.35)" }}>
            <Landmark size={28} color="#fff" strokeWidth={1.8} />
          </div>
          <h1 className="display" style={{ fontSize: 44 }}>Meridian</h1>
          <p style={{ color: "var(--text-2)", fontSize: 18, marginTop: 8, maxWidth: 420 }}>
            Private banking, protected by continuous trust —
            not a password someone can steal.
          </p>
          <button onClick={login} className="btn-primary mt-8"
            style={{ padding: "13px 34px", fontSize: 16 }}>
            Enter
          </button>
          <p className="label mt-5">no password · Cadence verifies it's really you</p>
        </motion.div>
      </div>
    );
  }

  const checking = accounts.find((a) => a.name === "checking")?.balance ?? 0;
  const savings = accounts.find((a) => a.name === "savings")?.balance ?? 0;
  const presencePct = liveScore == null ? null : Math.round(liveScore * 100);

  return (
    <div className="min-h-screen" style={{
      background: "radial-gradient(1100px 500px at 80% -10%, rgba(94,158,255,0.07), transparent 55%)",
    }}>
      <div className="max-w-[1120px] mx-auto px-7 py-7">
        {/* ---- header ---- */}
        <header className="flex items-center justify-between mb-9">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center"
              style={{ background: "linear-gradient(180deg,var(--accent),var(--accent-deep))" }}>
              <Landmark size={18} color="#fff" strokeWidth={1.9} />
            </div>
            <span className="display" style={{ fontSize: 20 }}>Meridian</span>
            <div className="flex items-center gap-2 ml-2">
              {backend === "nessie" && <Badge color="var(--green)" text="Capital One · live" />}
              {identity?.verified && (
                <Badge color="var(--accent)"
                  text={`${identity.name}${identity.credit_score ? ` · ${identity.credit_score} ${identity.credit_band}` : ""}`} />
              )}
            </div>
          </div>
          <PresencePill pct={presencePct} />
        </header>

        {/* ---- balances ---- */}
        <div className="grid grid-cols-2 gap-4 mb-5">
          <Balance name="Checking" value={checking} primary />
          <Balance name="Savings" value={savings} />
        </div>

        <div className="grid grid-cols-[minmax(0,420px)_1fr] gap-5 items-start max-[880px]:grid-cols-1">
          {/* ---- transfer composer ---- */}
          <section className="card p-7">
            <div className="label mb-5">Send money</div>
            <div className="flex flex-col gap-3">
              <Row label="From" value="Checking" />
              <Row label="To" value="Savings" />
              <div className="field px-4 py-3">
                <div className="label mb-1" style={{ fontSize: 10 }}>Amount</div>
                <div className="flex items-center gap-1">
                  <span className="display" style={{ fontSize: 26, color: "var(--text-2)" }}>$</span>
                  <input className="display" style={{ fontSize: 26 }} value={amount}
                    inputMode="decimal" onChange={(e) => setAmount(e.target.value)} />
                </div>
              </div>
              <div className="field px-4 py-3">
                <div className="label mb-1" style={{ fontSize: 10 }}>Memo</div>
                <input value={memo} placeholder="what's this for? (type naturally)"
                  onChange={(e) => setMemo(e.target.value)} style={{ fontSize: 16 }} />
              </div>
            </div>

            <label className="flex items-center gap-2.5 mt-5 cursor-pointer select-none"
              style={{ color: "var(--text-2)", fontSize: 13 }}>
              <input type="checkbox" checked={simRisky}
                onChange={(e) => setSimRisky(e.target.checked)}
                style={{ accentColor: "var(--amber)", width: 15, height: 15 }} />
              Demo: pretend I'm on a VPN / datacenter network
            </label>

            <button onClick={runTransfer} disabled={busy}
              className="btn-primary w-full mt-5 flex items-center justify-center gap-2"
              style={{ padding: "14px", fontSize: 16 }}>
              {busy ? <><Loader2 size={17} className="animate-spin" /> Verifying…</>
                : <>Send ${amount || "0"} <ArrowRight size={17} /></>}
            </button>

            {/* recovery actions — unmissable, plain language */}
            <AnimatePresence>
              {decision === "stepup" && !challenge && !kycOpen && (
                <RecoveryPanel recovery={recovery} reason={reason}
                  onTouch={touchId} touchState={touchState}
                  onKyc={() => setKycOpen(true)} />
              )}
              {challenge && (
                <ChallengePanel sentence={challenge} onDone={finishChallenge} />
              )}
              {kycOpen && (
                <KycPanel kyc={kyc} setKyc={setKyc} state={kycState} msg={kycMsg}
                  onSubmit={submitKyc} onSynthetic={() => { setKyc(SYNTH_P); setKycState("idle"); }}
                  onReset={() => { setKyc(PASS_P); setKycState("idle"); }} />
              )}
              {decision === "deny" && (
                <RecoveryPanel recovery={recovery} reason={reason}
                  onTouch={touchId} touchState={touchState}
                  onKyc={() => setKycOpen(true)} denied />
              )}
            </AnimatePresence>
          </section>

          {/* ---- verification result ---- */}
          <section className="flex flex-col gap-5">
            <DecisionCard phase={phase} decision={decision} reason={reason}
              trust={trust} behaviorScore={behaviorScore} />
            <SignalGrid factors={factors} active={!!decision || !!phase} />
          </section>
        </div>

        {/* ---- history ---- */}
        {history.length > 0 && (
          <section className="card p-6 mt-5">
            <div className="label mb-4">Recent activity</div>
            <div className="flex flex-col">
              {history.slice(0, 6).map((t, i) => (
                <div key={i} className="flex items-center justify-between py-2.5"
                  style={{ borderTop: i ? "1px solid var(--border)" : "none" }}>
                  <div className="flex items-center gap-3">
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: decisionColor(t.decision) }} />
                    <span style={{ fontSize: 15 }}>{t.memo || "Transfer to Savings"}</span>
                  </div>
                  <div className="flex items-center gap-6">
                    <span className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>
                      {t.score != null ? `${Math.round(t.score * 100)}% trust` : "—"}
                    </span>
                    <span className="mono" style={{ fontSize: 15, width: 90, textAlign: "right" }}>
                      ${t.amount.toFixed(2)}
                    </span>
                    <span className="label" style={{ width: 56, textAlign: "right",
                      color: decisionColor(t.decision) }}>{t.decision}</span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        <p className="label text-center mt-8" style={{ opacity: 0.6 }}>
          Every transfer scored across four signals · behavior never leaves the device · server sees only a signed decision
        </p>
      </div>
    </div>
  );
}

// ---------- components ----------

function Badge({ color, text }: { color: string; text: string }) {
  return (
    <span className="glass px-2.5 py-1 flex items-center gap-1.5"
      style={{ borderRadius: 999, fontSize: 11.5, color }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />
      {text}
    </span>
  );
}

function PresencePill({ pct }: { pct: number | null }) {
  const col = pct == null ? "var(--muted)" : pct >= 70 ? "var(--green)"
    : pct >= 40 ? "var(--amber)" : "var(--red)";
  const word = pct == null ? "Sensing…" : pct >= 70 ? "You're present"
    : pct >= 40 ? "Uncertain" : "Not recognized";
  return (
    <div className="glass flex items-center gap-2.5 px-3.5 py-2" style={{ borderRadius: 999 }}>
      <Activity size={14} color={col} />
      <span style={{ fontSize: 13, color: "var(--text-2)" }}>{word}</span>
      <span className="mono" style={{ fontSize: 13, color: col }}>{pct == null ? "—" : `${pct}%`}</span>
    </div>
  );
}

function Balance({ name, value, primary }: { name: string; value: number; primary?: boolean }) {
  return (
    <div className="card p-5" style={primary ? { borderColor: "var(--border-2)" } : undefined}>
      <div className="label mb-1.5">{name}</div>
      <div className="display mono" style={{ fontSize: 30 }}>
        ${value.toLocaleString(undefined, { minimumFractionDigits: 2 })}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="field px-4 py-3 flex items-center justify-between">
      <span className="label" style={{ fontSize: 10 }}>{label}</span>
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

function DecisionCard({ phase, decision, reason, trust, behaviorScore }: {
  phase: string; decision: Decision | null; reason: string;
  trust: number | null; behaviorScore: number | null;
}) {
  const col = decisionColor(decision);
  const title = decision === "allow" ? "Transfer approved"
    : decision === "stepup" ? "One more check needed"
    : decision === "deny" ? "Transfer blocked" : "Ready when you are";
  return (
    <div className="card p-7 relative overflow-hidden">
      <div className="absolute inset-0 pointer-events-none" style={{
        background: decision ? `radial-gradient(420px 180px at 100% 0%, ${col}14, transparent 70%)` : "none" }} />
      <div className="relative flex items-center gap-6">
        <TrustRing value={decision ? trust : null} decision={decision} />
        <div className="flex-1 min-w-0">
          <AnimatePresence mode="wait">
            <motion.div key={(decision ?? "") + phase}
              initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }} transition={SPRING}>
              <div className="display" style={{ fontSize: 24, color: decision ? col : "var(--text)" }}>
                {phase ? "Verifying…" : title}
              </div>
              <p style={{ color: "var(--text-2)", fontSize: 14.5, marginTop: 4, lineHeight: 1.45 }}>
                {phase ? PHASE_STEPS.find((s) => s.key === phase)?.label
                  : decision ? reason
                  : "Compose a transfer and Cadence will score it live."}
              </p>
              {behaviorScore != null && decision && (
                <div className="mono mt-2.5" style={{ fontSize: 12, color: "var(--muted)" }}>
                  behavioral presence {Math.round(behaviorScore * 100)}% · ES256 signed · nonce-bound
                </div>
              )}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
      {phase && (
        <div className="mt-6 flex flex-col gap-2">
          {PHASE_STEPS.map((s) => {
            const idx = PHASE_STEPS.findIndex((x) => x.key === phase);
            const si = PHASE_STEPS.findIndex((x) => x.key === s.key);
            const done = si < idx, active = si === idx;
            return (
              <div key={s.key} className="flex items-center gap-3"
                style={{ opacity: done || active ? 1 : 0.35 }}>
                {done ? <Check size={15} color="var(--green)" />
                  : active ? <Loader2 size={15} className="animate-spin" color="var(--accent)" />
                  : <span className="w-[15px]" />}
                <span style={{ fontSize: 13.5, color: active ? "var(--text)" : "var(--text-2)" }}>
                  {s.label}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function SignalGrid({ factors, active }: { factors: Factor[]; active: boolean }) {
  return (
    <div className="grid grid-cols-2 gap-4 max-[520px]:grid-cols-1">
      {DIMENSIONS.map(({ key, icon: Icon, blurb }) => {
        const fs = factors.filter((f) => f.dimension === key);
        const worst = fs.some((f) => f.severity === "bad") ? "bad"
          : fs.some((f) => f.severity === "warn") ? "warn"
          : fs.length ? "ok" : "idle";
        const col = worst === "idle" ? "var(--muted)" : sevColor(worst);
        return (
          <motion.div key={key} layout className="card p-5"
            style={{ borderColor: worst === "idle" ? "var(--border)" : col + "44",
                     opacity: active ? 1 : 0.5 }}>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2.5">
                <Icon size={17} color={col} strokeWidth={1.9} />
                <span style={{ fontSize: 14.5, fontWeight: 560 }}>{key}</span>
              </div>
              <span className="w-2 h-2 rounded-full" style={{ background: col,
                boxShadow: worst !== "idle" && worst !== "ok" ? `0 0 8px ${col}` : "none" }} />
            </div>
            {fs.length === 0 ? (
              <p style={{ fontSize: 12.5, color: "var(--muted)" }}>{blurb}</p>
            ) : (
              <div className="flex flex-col gap-2">
                {fs.map((f, i) => (
                  <div key={i}>
                    <div style={{ fontSize: 13, fontWeight: 560, color: sevColor(f.severity) }}>{f.label}</div>
                    <div style={{ fontSize: 12, color: "var(--text-2)", lineHeight: 1.4 }}>{f.detail}</div>
                  </div>
                ))}
              </div>
            )}
          </motion.div>
        );
      })}
    </div>
  );
}

function RecoveryPanel({ recovery, reason, onTouch, touchState, onKyc, denied }: {
  recovery: string[]; reason: string; onTouch: () => void;
  touchState: string; onKyc: () => void; denied?: boolean;
}) {
  return (
    <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
      <div className="mt-5 p-4 rounded-2xl" style={{
        background: "var(--bg-2)", border: `1px solid ${denied ? "var(--red)" : "var(--amber)"}44` }}>
        <p style={{ fontSize: 14, color: "var(--text-2)", marginBottom: 12 }}>
          {denied ? "This doesn't look like the account owner. If it's really you, prove it:"
            : "Cadence isn't fully sure — one quick confirmation and you're through:"}
        </p>
        <div className="flex flex-col gap-2.5">
          {recovery.includes("touchid") && (
            <button onClick={onTouch} disabled={touchState === "waiting"}
              className="btn-ghost flex items-center gap-3 px-4 py-3 text-left"
              style={{ borderColor: "var(--border-2)" }}>
              <ScanFace size={19} color="var(--accent)" />
              <div className="flex-1">
                <div style={{ fontSize: 14.5, fontWeight: 560 }}>
                  {touchState === "waiting" ? "Waiting for the sensor…"
                    : touchState === "failed" ? "Touch ID didn't match — try again"
                    : "Confirm with Touch ID"}</div>
                <div style={{ fontSize: 12, color: "var(--text-2)" }}>hardware biometric on this Mac</div>
              </div>
              <ArrowRight size={16} color="var(--muted)" />
            </button>
          )}
          {recovery.includes("kyc") && (
            <button onClick={onKyc} className="btn-ghost flex items-center gap-3 px-4 py-3 text-left">
              <ShieldCheck size={19} color="var(--accent)" />
              <div className="flex-1">
                <div style={{ fontSize: 14.5, fontWeight: 560 }}>Verify identity</div>
                <div style={{ fontSize: 12, color: "var(--text-2)" }}>bureau-grade check via CRS</div>
              </div>
              <ArrowRight size={16} color="var(--muted)" />
            </button>
          )}
        </div>
      </div>
    </motion.div>
  );
}

function ChallengePanel({ sentence, onDone }: { sentence: string; onDone: () => void }) {
  const [text, setText] = useState("");
  return (
    <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
      <div className="mt-5 p-4 rounded-2xl" style={{ background: "var(--bg-2)", border: "1px solid var(--amber)44" }}>
        <div className="label mb-2" style={{ color: "var(--amber)" }}>Type this sentence, naturally</div>
        <div style={{ fontSize: 15.5, marginBottom: 10 }}>{sentence}</div>
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} autoFocus
          placeholder="type here…"
          className="w-full field px-4 py-2.5" style={{ fontSize: 15, resize: "none" }} />
        <button onClick={onDone} disabled={text.length < 10}
          className="btn-primary mt-3 px-5 py-2.5" style={{ fontSize: 14 }}>Re-verify</button>
      </div>
    </motion.div>
  );
}

function KycPanel({ kyc, setKyc, state, msg, onSubmit, onSynthetic, onReset }: {
  kyc: Record<string, string>; setKyc: (k: Record<string, string>) => void;
  state: string; msg: string; onSubmit: () => void; onSynthetic: () => void; onReset: () => void;
}) {
  const fields: [string, string][] = [["First name", "firstName"], ["Last name", "lastName"],
    ["SSN", "ssn"], ["Date of birth", "dob"], ["Street", "street1"], ["City", "city"],
    ["State", "state"], ["ZIP", "zip"]];
  return (
    <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
      <div className="mt-5 p-4 rounded-2xl" style={{ background: "var(--bg-2)", border: "1px solid var(--accent)44" }}>
        <div className="label mb-1" style={{ color: "var(--accent)" }}>Identity verification · CRS</div>
        <p style={{ fontSize: 13, color: "var(--text-2)", marginBottom: 12 }}>
          High-value transfer — we confirm the account holder against the credit bureaus.</p>
        <div className="grid grid-cols-2 gap-2">
          {fields.map(([label, k]) => (
            <input key={k} value={kyc[k]} placeholder={label}
              onChange={(e) => setKyc({ ...kyc, [k]: e.target.value })}
              className="field px-3 py-2.5" style={{ fontSize: 13.5 }} />
          ))}
        </div>
        {state === "failed" && (
          <div style={{ fontSize: 12.5, color: "var(--red)", marginTop: 8 }}>TransUnion: {msg}</div>
        )}
        <div className="flex items-center gap-3 mt-3 flex-wrap">
          <button onClick={onSubmit} disabled={state === "checking"}
            className="btn-primary px-5 py-2.5" style={{ fontSize: 14 }}>
            {state === "checking" ? "Verifying with CRS…" : "Verify identity"}</button>
          <button onClick={onSynthetic} className="label hover:opacity-100"
            style={{ opacity: 0.7 }}>demo: synthetic identity</button>
          <button onClick={onReset} className="label hover:opacity-100" style={{ opacity: 0.7 }}>reset</button>
        </div>
      </div>
    </motion.div>
  );
}
