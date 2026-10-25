import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowRight, Check, Loader2, ScanFace, ShieldCheck, Wallet, Send,
  UsersRound, Clock, Lock, CreditCard, Plus, Activity, Fingerprint, Landmark,
} from "lucide-react";

const SPRING = { type: "spring", stiffness: 300, damping: 32 } as const;
const BANK = `http://${location.hostname || "127.0.0.1"}:7900`;
const VERIFIER = `http://${location.hostname || "127.0.0.1"}:7800`;
const DAEMON = "http://127.0.0.1:7777";

type Decision = "allow" | "stepup" | "deny";
type Factor = { dimension: string; label: string; detail: string; severity: string };
type Transfer = { ts: number; to: string; amount: number; memo: string; decision: Decision; score: number | null };

const DIM_ACCENT: Record<string, string> = { Presence: "var(--forest)", Identity: "var(--periwinkle)", Device: "var(--candy)", Transaction: "var(--butter)" };
const DIMS = ["Presence", "Identity", "Device", "Transaction"] as const;
const DIM_BLURB: Record<string, string> = { Presence: "Is the enrolled human here?", Identity: "Real, non-synthetic person?", Device: "Trusted device and network?", Transaction: "Normal for this account?" };
const decColor = (d: string | null) => d === "allow" ? "var(--forest)" : d === "stepup" ? "var(--amber-ink)" : d === "deny" ? "var(--crimson)" : "var(--muted)";
const sevColor = (s: string) => s === "ok" ? "var(--forest)" : s === "warn" ? "var(--amber-ink)" : "var(--crimson)";
const fmt = (n: number) => n.toLocaleString(undefined, { minimumFractionDigits: 2 });

const RECIPIENTS = [
  { name: "Savings", sub: "Capital One · ••4021", initial: "SV", known: true },
  { name: "Elena Castellanos", sub: "Chase · ••7788", initial: "EC", known: true },
  { name: "Northwind Properties", sub: "rent · ••1140", initial: "NP", known: true },
  { name: "Daniel Whitfield", sub: "Capital One · ••9032", initial: "DW", known: true },
];

function deviceFingerprint(): string {
  try {
    const c = document.createElement("canvas"); const ctx = c.getContext("2d");
    if (ctx) { ctx.textBaseline = "top"; ctx.font = "14px Arial"; ctx.fillStyle = "#f60"; ctx.fillRect(0, 0, 60, 20); ctx.fillStyle = "#069"; ctx.fillText("cadence", 2, 2); }
    const bits = [c.toDataURL(), navigator.userAgent, navigator.language, `${screen.width}x${screen.height}`, new Date().getTimezoneOffset()].join("|");
    let h = 0; for (let i = 0; i < bits.length; i++) { h = (h << 5) - h + bits.charCodeAt(i); h |= 0; } return "fp" + Math.abs(h).toString(36);
  } catch { return "fp-x"; }
}

export default function App() {
  const [hash, setHashState] = useState(location.hash);
  const [loggedIn, setLoggedIn] = useState(false);
  const [view, setView] = useState<"accounts" | "pay" | "recipients" | "activity" | "security">("accounts");
  const [backend, setBackend] = useState("mock");
  const [accounts, setAccounts] = useState<{ name: string; balance: number }[]>([]);
  const [amount, setAmount] = useState("500");
  const [memo, setMemo] = useState("");
  const [payee, setPayee] = useState("Savings");
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<"nonce" | "attest" | "sign" | "risk" | "">("");
  const [decision, setDecision] = useState<Decision | null>(null);
  const [reason, setReason] = useState("");
  const [factors, setFactors] = useState<Factor[]>([]);
  const [trust, setTrust] = useState<number | null>(null);
  const [recovery, setRecovery] = useState<string[]>([]);
  const [history, setHistory] = useState<Transfer[]>([]);
  const [identity, setIdentity] = useState<{ name: string; verified: boolean; credit_score?: number; credit_band?: string; fraud_risk?: number } | null>(null);
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

  useEffect(() => { const h = () => setHashState(location.hash); addEventListener("hashchange", h); return () => removeEventListener("hashchange", h); }, []);
  const refresh = useCallback(() => {
    fetch(`${BANK}/accounts`, { credentials: "include" }).then((r) => r.ok ? r.json() : Promise.reject()).then((j) => { setAccounts(j.accounts); setBackend(j.backend ?? "mock"); setLoggedIn(true); }).catch(() => {});
    fetch(`${BANK}/transfers`).then((r) => r.json()).then((j) => { setHistory(j.transfers); histRef.current = j.transfers; }).catch(() => {});
    fetch(`${DAEMON}/status`).then((r) => r.json()).then((s) => fetch(`${VERIFIER}/identity/${s.device_id}`)).then((r) => r.json()).then((j) => setIdentity(j.identity ?? null)).catch(() => {});
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { const es = new EventSource(`${DAEMON}/events`); es.addEventListener("score", (e) => { try { setLiveScore(JSON.parse((e as MessageEvent).data).score); } catch { /* */ } }); return () => es.close(); }, []);

  const login = async () => { await fetch(`${BANK}/login`, { method: "POST", credentials: "include" }); refresh(); };
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  const runTransfer = async () => {
    setBusy(true); setDecision(null); setChallenge(null); setKycOpen(false); setTouchState("idle"); setFactors([]);
    try {
      setPhase("nonce"); const { nonce } = await (await fetch(`${VERIFIER}/nonce`)).json(); await sleep(280); setPhase("attest");
      const ar = await fetch(`${DAEMON}/attest?nonce=${encodeURIComponent(nonce)}`);
      if (!ar.ok) { setPhase(""); setDecision("deny"); setReason("No behavioral signal yet — type in the memo so Cadence can sense you."); setRecovery([]); return; }
      const att = await ar.json(); await sleep(280); setPhase("sign"); await sleep(280); setPhase("risk");
      const res = await (await fetch(`${BANK}/transfer`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ to: payee, amount: parseFloat(amount) || 0, memo, jws: att.jws, fingerprint: deviceFingerprint(), client_ip: simRisky ? "52.14.88.3" : "", user_agent: navigator.userAgent, history: histRef.current.filter((h) => h.decision === "allow").map((h) => ({ amount: h.amount, to: h.to, ts: h.ts })) }) })).json();
      await sleep(420);
      const d = (res.decision as Decision) ?? "deny";
      setFactors(res.factors ?? []); setTrust(res.trust ?? null); setDecision(d); setReason(res.reason ?? ""); setRecovery(res.recovery ?? []); setPhase("");
      if (res.identity) setIdentity(res.identity);
      if (d === "stepup" && (res.recovery ?? []).includes("challenge")) { const sj = await (await fetch(`${DAEMON}/stepup/start`, { method: "POST" })).json(); setChallenge(sj.challenge); }
      else if (d === "stepup" && res.kyc_required) setKycOpen(true);
      refresh();
    } finally { setBusy(false); }
  };
  const finishChallenge = async () => { await fetch(`${DAEMON}/stepup/finish`, { method: "POST" }); try { const st = await (await fetch(`${DAEMON}/status`)).json(); await fetch(`${VERIFIER}/challenge`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ device_id: st.device_id }) }); } catch { /* */ } setChallenge(null); await runTransfer(); };
  const touchId = async () => { setTouchState("waiting"); try { const j = await (await fetch(`${DAEMON}/touchid`, { method: "POST" })).json(); if (j.ok) { setTouchState("idle"); await runTransfer(); } else setTouchState("failed"); } catch { setTouchState("failed"); } };
  const submitKyc = async () => { setKycState("checking"); try { const st = await (await fetch(`${DAEMON}/status`)).json(); const j = await (await fetch(`${VERIFIER}/kyc`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ device_id: st.device_id, ...kyc }) })).json(); if (j.verified) { setKycOpen(false); setKycState("idle"); setKycMsg(""); await runTransfer(); } else { setKycState("failed"); setKycMsg((j.messages ?? []).map((m: { text: string }) => m.text).join(" · ") || "Identity could not be verified."); } } catch { setKycState("failed"); setKycMsg("Verification service unreachable."); } };

  const presencePct = liveScore == null ? null : Math.round(liveScore * 100);

  // ---------- onboarding (signup) ----------
  if (hash.startsWith("#/welcome")) return <Onboarding onDone={() => { location.hash = ""; login(); }} identity={identity} login={login} />;

  // ---------- login ----------
  if (!loggedIn) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center px-6" style={{ background: "var(--bone)" }}>
        <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={SPRING} className="text-center" style={{ maxWidth: 580 }}>
          <div className="label mb-7" style={{ letterSpacing: "0.12em" }}>Capital One · digital banking</div>
          <h1 className="display" style={{ fontSize: 56, lineHeight: 1.06 }}>The account<br />only you can use.</h1>
          <p style={{ fontSize: 18, color: "var(--muted)", marginTop: 18, lineHeight: 1.5 }}>Capital One verifies every payment by how you type and move. A stolen password, device, or session moves nothing.</p>
          <button onClick={login} className="pill mt-8" style={{ padding: "13px 34px", fontSize: 16 }}>Sign in</button>
        </motion.div>
      </div>
    );
  }

  const checking = accounts.find((a) => a.name === "checking")?.balance ?? 0;
  const savings = accounts.find((a) => a.name === "savings")?.balance ?? 0;
  const nav = [["accounts", "Accounts", Wallet], ["pay", "Pay", Send], ["recipients", "Recipients", UsersRound], ["activity", "Activity", Clock], ["security", "Security", Lock]] as const;

  return (
    <div className="min-h-screen flex" style={{ background: "var(--bone)" }}>
      {/* sidebar */}
      <aside className="flex flex-col shrink-0" style={{ width: 236, background: "var(--paper)", borderRight: "1px solid var(--line)" }}>
        <div className="flex items-center gap-2.5" style={{ padding: "24px 22px 24px" }}>
          <div className="w-8 h-8 rounded-[10px] flex items-center justify-center" style={{ background: "var(--ink)" }}><Landmark size={16} color="#fff" strokeWidth={2} /></div>
          <span className="display" style={{ fontSize: 19 }}>Capital One</span>
        </div>
        <nav className="flex flex-col gap-0.5 px-3">
          {nav.map(([id, label, Icon]) => { const a = view === id; return (
            <button key={id} onClick={() => setView(id)} className="flex items-center gap-3 px-3.5 py-2.5 rounded-lg transition text-left"
              style={{ background: a ? "var(--bone)" : "transparent", color: a ? "var(--ink)" : "var(--muted)" }}>
              <Icon size={16.5} strokeWidth={1.9} color={a ? "var(--ink)" : "var(--muted)"} /><span style={{ fontSize: 14, fontWeight: a ? 500 : 400 }}>{label}</span></button>); })}
        </nav>
        <div className="mt-auto px-4 pb-5">
          <div className="rounded-xl p-3.5" style={{ border: "1px solid var(--line)" }}>
            <PresenceInline pct={presencePct} />
            {identity?.verified && <div className="label mt-2.5" style={{ fontSize: 9.5 }}>{identity.name} · verified</div>}
          </div>
        </div>
      </aside>

      {/* main */}
      <main className="flex-1 min-w-0" style={{ padding: "30px 40px" }}>
        <div className="flex items-center justify-between mb-7">
          <h1 className="display" style={{ fontSize: 26, textTransform: "capitalize" }}>{view}</h1>
          <div className="flex items-center gap-2">
            {backend === "nessie" && <Chip dot="var(--forest)" text="Capital One · live" />}
            {identity?.verified && <Chip dot="var(--periwinkle)" text={`${identity.credit_score ?? ""} ${identity.credit_band ?? ""} · CRS`} />}
          </div>
        </div>

        {view === "accounts" && <Accounts checking={checking} savings={savings} history={history} identity={identity} onPay={() => setView("pay")} />}
        {view === "recipients" && <Recipients onPay={(n) => { setPayee(n); setView("pay"); }} />}
        {view === "activity" && <ActivityView history={history} />}
        {view === "security" && <Security identity={identity} pct={presencePct} backend={backend} />}
        {view === "pay" && (
          <div className="grid gap-5" style={{ gridTemplateColumns: "minmax(0,400px) 1fr" }}>
            <section className="card" style={{ padding: 26 }}>
              <div className="label mb-5">Send money</div>
              <div className="flex flex-col gap-3">
                <Row label="From" value="Checking · ••2213" />
                <button onClick={() => setView("recipients")} className="field flex items-center justify-between text-left" style={{ padding: "11px 16px" }}>
                  <span className="label" style={{ fontSize: 10.5 }}>To</span><span style={{ fontSize: 16 }}>{payee} <ArrowRight size={13} style={{ display: "inline", marginLeft: 4, opacity: 0.4 }} /></span></button>
                <div className="field" style={{ padding: "11px 16px" }}><div className="label" style={{ fontSize: 10.5, marginBottom: 3 }}>Amount</div>
                  <div className="flex items-center gap-1.5"><span className="display" style={{ fontSize: 26, color: "var(--muted)" }}>$</span><input className="display" style={{ fontSize: 26 }} value={amount} inputMode="decimal" onChange={(e) => setAmount(e.target.value)} /></div></div>
                <div className="field" style={{ padding: "11px 16px" }}><div className="label" style={{ fontSize: 10.5, marginBottom: 3 }}>Memo</div>
                  <input value={memo} placeholder="what's this for?" onChange={(e) => setMemo(e.target.value)} style={{ fontSize: 16 }} /></div>
              </div>
              <label className="flex items-center gap-2.5 mt-5 cursor-pointer select-none" style={{ color: "var(--muted)", fontSize: 13 }}>
                <input type="checkbox" checked={simRisky} onChange={(e) => setSimRisky(e.target.checked)} style={{ accentColor: "var(--ink)", width: 15, height: 15 }} />Demo: simulate a VPN / datacenter network</label>
              <button onClick={runTransfer} disabled={busy} className="pill w-full mt-5 flex items-center justify-center gap-2" style={{ padding: 14, fontSize: 16 }}>
                {busy ? <><Loader2 size={17} className="animate-spin" /> Verifying…</> : <>Send ${amount || "0"} <ArrowRight size={16} /></>}</button>
              <AnimatePresence>
                {decision === "stepup" && !challenge && !kycOpen && <Recovery recovery={recovery} onTouch={touchId} touchState={touchState} onKyc={() => setKycOpen(true)} />}
                {decision === "deny" && <Recovery recovery={recovery} onTouch={touchId} touchState={touchState} onKyc={() => setKycOpen(true)} denied />}
                {challenge && <ChallengeBox sentence={challenge} onDone={finishChallenge} />}
                {kycOpen && <KycBox kyc={kyc} setKyc={setKyc} state={kycState} msg={kycMsg} onSubmit={submitKyc} onSynthetic={() => { setKyc(SYNTH_P); setKycState("idle"); }} onReset={() => { setKyc(PASS_P); setKycState("idle"); }} />}
              </AnimatePresence>
            </section>
            <section className="flex flex-col gap-5">
              <DecisionCard phase={phase} decision={decision} reason={reason} trust={trust} />
              <div className="grid grid-cols-2 gap-5">{DIMS.map((dim) => <SignalCard key={dim} dim={dim} factors={factors.filter((f) => f.dimension === dim)} active={!!decision} />)}</div>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}

// ---------- onboarding ----------
function Onboarding({ onDone, identity, login }: { onDone: () => void; identity: { credit_score?: number; credit_band?: string } | null; login: () => void }) {
  const [step, setStep] = useState(0);
  const [idState, setIdState] = useState<"idle" | "checking" | "done">("idle");
  const [linkState, setLinkState] = useState<"idle" | "checking" | "done">("idle");
  const [trainPct, setTrainPct] = useState(0);
  useEffect(() => { login(); }, [login]);
  const steps = ["Verify identity", "Link your bank", "Train your profile", "Protected"];
  const doId = async () => { setIdState("checking"); await new Promise((r) => setTimeout(r, 1400)); setIdState("done"); setTimeout(() => setStep(1), 700); };
  const doLink = async () => { setLinkState("checking"); await new Promise((r) => setTimeout(r, 1500)); setLinkState("done"); setTimeout(() => setStep(2), 700); };
  const doTrain = async () => { for (let p = 0; p <= 100; p += 4) { setTrainPct(p); await new Promise((r) => setTimeout(r, 55)); } setTrainPct(100); setTimeout(() => setStep(3), 600); };
  return (
    <div className="min-h-screen flex flex-col items-center" style={{ background: "var(--bone)", paddingTop: 72 }}>
      <div className="label mb-6" style={{ letterSpacing: "0.12em" }}>Capital One · open an account</div>
      <div className="flex items-center gap-2 mb-10">
        {steps.map((s, i) => (<div key={s} className="flex items-center gap-2">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full" style={{ border: `1px solid ${i <= step ? "var(--ink)" : "var(--line)"}`, color: i <= step ? "var(--ink)" : "var(--muted)" }}>
            {i < step ? <Check size={13} /> : <span className="mono" style={{ fontSize: 12 }}>{i + 1}</span>}<span style={{ fontSize: 13 }}>{s}</span></div>
          {i < steps.length - 1 && <div style={{ width: 24, height: 1, background: "var(--line)" }} />}</div>))}
      </div>
      <AnimatePresence mode="wait">
        <motion.div key={step} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} transition={SPRING} className="card" style={{ width: 460, padding: 32 }}>
          {step === 0 && (<>
            <ScanFace size={26} color="var(--forest)" /><h2 className="display" style={{ fontSize: 24, marginTop: 14 }}>Verify your identity</h2>
            <p style={{ fontSize: 14.5, color: "var(--muted)", marginTop: 6 }}>Checked against the credit bureaus through CRS · TransUnion. Takes a few seconds.</p>
            <div className="mt-5 flex flex-col gap-2">{[["Name", "Margaret Okafor"], ["SSN", "•••-••-1001"], ["Address", "San Jose, CA"]].map(([k, v]) => (
              <div key={k} className="field flex items-center justify-between" style={{ padding: "10px 14px" }}><span className="label" style={{ fontSize: 10 }}>{k}</span><span style={{ fontSize: 14.5 }}>{v}</span></div>))}</div>
            <button onClick={doId} disabled={idState !== "idle"} className="pill w-full mt-6 flex items-center justify-center gap-2" style={{ padding: 13, fontSize: 15 }}>
              {idState === "checking" ? <><Loader2 size={16} className="animate-spin" /> Verifying with CRS…</> : idState === "done" ? <><Check size={16} /> Identity verified</> : "Verify identity"}</button>
          </>)}
          {step === 1 && (<>
            <Landmark size={26} color="var(--forest)" /><h2 className="display" style={{ fontSize: 24, marginTop: 14 }}>Link your bank</h2>
            <p style={{ fontSize: 14.5, color: "var(--muted)", marginTop: 6 }}>Connected through the Nessie API. Your credentials never leave Capital One.</p>
            <div className="mt-5 field flex items-center gap-3" style={{ padding: "14px 16px" }}>
              <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: "var(--elevated)" }}><CreditCard size={17} /></div>
              <div><div style={{ fontSize: 15 }}>Capital One</div><div style={{ fontSize: 12.5, color: "var(--muted)" }}>Checking + Savings</div></div>
              {linkState === "done" && <Check size={18} color="var(--forest)" className="ml-auto" />}</div>
            <button onClick={doLink} disabled={linkState !== "idle"} className="pill w-full mt-6 flex items-center justify-center gap-2" style={{ padding: 13, fontSize: 15 }}>
              {linkState === "checking" ? <><Loader2 size={16} className="animate-spin" /> Connecting…</> : linkState === "done" ? <><Check size={16} /> Connected</> : "Connect Capital One"}</button>
          </>)}
          {step === 2 && (<>
            <Fingerprint size={26} color="var(--forest)" /><h2 className="display" style={{ fontSize: 24, marginTop: 14 }}>Train your profile</h2>
            <p style={{ fontSize: 14.5, color: "var(--muted)", marginTop: 6 }}>Type naturally for a minute. Cadence builds a behavioral model — our own, pretrained on 136M keystrokes — that recognizes only you.</p>
            <div className="mt-6"><div className="flex items-center justify-between mb-2"><span className="label">Enrolling</span><span className="mono" style={{ fontSize: 13 }}>{trainPct}%</span></div>
              <div className="w-full rounded-full overflow-hidden" style={{ height: 6, background: "var(--elevated)" }}><motion.div style={{ height: "100%", background: "var(--forest)", width: `${trainPct}%` }} /></div></div>
            <button onClick={doTrain} disabled={trainPct > 0} className="pill w-full mt-6 flex items-center justify-center gap-2" style={{ padding: 13, fontSize: 15 }}>{trainPct > 0 ? "Learning your rhythm…" : "Start enrollment"}</button>
          </>)}
          {step === 3 && (<div className="text-center">
            <div className="mx-auto w-14 h-14 rounded-full flex items-center justify-center" style={{ background: "color-mix(in srgb, var(--forest) 12%, transparent)" }}><Check size={28} color="var(--forest)" /></div>
            <h2 className="display" style={{ fontSize: 24, marginTop: 16 }}>You're protected.</h2>
            <p style={{ fontSize: 14.5, color: "var(--muted)", marginTop: 6 }}>Identity verified, bank linked, behavioral model trained. Every payment is now scored by how you bank.</p>
            <button onClick={onDone} className="pill mt-7" style={{ padding: "12px 28px", fontSize: 15 }}>Enter Capital One</button></div>)}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

// ---------- account views ----------
function Accounts({ checking, savings, history, identity, onPay }: { checking: number; savings: number; history: Transfer[]; identity: { credit_score?: number } | null; onPay: () => void }) {
  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-5" style={{ gridTemplateColumns: "1fr 1fr 340px" }}>
        <BalanceCard name="Checking" sub="••2213" value={checking} />
        <BalanceCard name="Savings" sub="••4021" value={savings} />
        <CardVisual name="Margaret Okafor" />
      </div>
      <div className="flex gap-3">
        <button onClick={onPay} className="pill flex items-center gap-2" style={{ padding: "11px 22px", fontSize: 15 }}><Send size={15} /> Send money</button>
        <button className="pill-ghost flex items-center gap-2" style={{ padding: "11px 22px", fontSize: 15 }}><Plus size={15} /> Add recipient</button>
      </div>
      <section className="card" style={{ padding: 26 }}>
        <div className="label mb-4">Recent activity</div>
        {history.length === 0 && <div style={{ color: "var(--muted)", fontSize: 14 }}>No activity yet.</div>}
        {history.slice(0, 7).map((t, i) => <ActivityRow key={i} t={t} first={i === 0} />)}
      </section>
    </div>
  );
}
function BalanceCard({ name, sub, value }: { name: string; sub: string; value: number }) {
  return (<div className="card" style={{ padding: 22 }}><div className="flex items-center justify-between mb-2"><div className="label">{name}</div><div className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>{sub}</div></div>
    <div className="display tnum" style={{ fontSize: 32 }}>${fmt(value)}</div><div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 4 }}>Available balance</div></div>);
}
function CardVisual({ name }: { name: string }) {
  return (<div className="rounded-2xl flex flex-col justify-between" style={{ padding: 22, background: "var(--ink)", color: "#fff", minHeight: 150 }}>
    <div className="flex items-center justify-between"><span style={{ fontSize: 14, opacity: 0.8 }}>Capital One</span><CreditCard size={20} /></div>
    <div><div className="mono" style={{ fontSize: 16, letterSpacing: "0.12em" }}>•••• •••• •••• 2213</div>
      <div className="flex items-center justify-between mt-2" style={{ fontSize: 12, opacity: 0.8 }}><span>{name}</span><span>12 / 28</span></div></div></div>);
}
function ActivityRow({ t, first }: { t: Transfer; first: boolean }) {
  return (<div className="flex items-center justify-between" style={{ padding: "11px 0", borderTop: first ? "none" : "1px solid var(--line)" }}>
    <div className="flex items-center gap-3"><span style={{ width: 3, height: 28, borderRadius: 2, background: decColor(t.decision) }} />
      <div><div style={{ fontSize: 15 }}>{t.memo || `Transfer to ${t.to}`}</div><div style={{ fontSize: 12, color: "var(--muted)" }}>to {t.to}</div></div></div>
    <div className="flex items-center gap-7"><span className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>{t.score != null ? `${Math.round(t.score * 100)}% trust` : "—"}</span>
      <span className="mono" style={{ fontSize: 15, width: 96, textAlign: "right" }}>${fmt(t.amount)}</span>
      <span className="label" style={{ width: 54, textAlign: "right", color: decColor(t.decision) }}>{t.decision}</span></div></div>);
}
function Recipients({ onPay }: { onPay: (name: string) => void }) {
  return (<div className="card" style={{ padding: 10 }}>
    {RECIPIENTS.map((r, i) => (<button key={r.name} onClick={() => onPay(r.name)} className="flex items-center gap-3 w-full text-left px-4 py-3.5 rounded-lg transition hover:bg-[var(--bone)]" style={{ borderBottom: i < RECIPIENTS.length - 1 ? "1px solid var(--line)" : "none" }}>
      <div className="w-10 h-10 rounded-full flex items-center justify-center" style={{ background: "var(--elevated)", fontSize: 13, fontWeight: 500 }}>{r.initial}</div>
      <div className="flex-1"><div style={{ fontSize: 15 }}>{r.name}</div><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{r.sub}</div></div>
      <span className="label flex items-center gap-1.5" style={{ color: "var(--forest)" }}><Check size={12} /> known</span>
      <Send size={15} color="var(--muted)" /></button>))}
  </div>);
}
function ActivityView({ history }: { history: Transfer[] }) {
  return (<section className="card" style={{ padding: 26 }}><div className="label mb-4">All activity</div>
    {history.length === 0 && <div style={{ color: "var(--muted)", fontSize: 14 }}>No activity yet.</div>}
    {history.map((t, i) => <ActivityRow key={i} t={t} first={i === 0} />)}</section>);
}
function Security({ identity, pct, backend }: { identity: { name: string; verified: boolean; credit_score?: number; credit_band?: string; fraud_risk?: number } | null; pct: number | null; backend: string }) {
  const rows = [
    ["Behavioral presence", pct == null ? "sensing…" : pct >= 70 ? `recognized · ${pct}%` : `uncertain · ${pct}%`, pct != null && pct >= 70],
    ["Identity", identity?.verified ? `${identity.name} · verified (CRS · TransUnion)` : "not verified", !!identity?.verified],
    ["Fraud screening", identity?.fraud_risk != null ? `CRS Fraud Finder · ${identity.fraud_risk}/100 risk` : "—", (identity?.fraud_risk ?? 100) < 40],
    ["Device", "MacBook Pro · Secure Enclave key", true],
    ["Bank link", backend === "nessie" ? "Capital One · connected" : "mock", backend === "nessie"],
  ] as const;
  return (<div className="flex flex-col gap-5" style={{ maxWidth: 680 }}>
    <div className="card" style={{ padding: 26 }}><div className="flex items-center gap-2.5 mb-5"><ShieldCheck size={20} color="var(--forest)" /><span style={{ fontSize: 17, fontWeight: 500 }}>Protected by Cadence</span></div>
      {rows.map(([label, val, ok], i) => (<div key={label} className="flex items-center justify-between" style={{ padding: "13px 0", borderTop: i ? "1px solid var(--line)" : "none" }}>
        <span style={{ fontSize: 14.5 }}>{label}</span><span className="flex items-center gap-2" style={{ fontSize: 13.5, color: ok ? "var(--forest)" : "var(--muted)" }}>{ok && <Check size={14} />}{val}</span></div>))}
    </div></div>);
}

// ---------- shared ----------
function Chip({ dot, text }: { dot: string; text: string }) {
  return (<span className="flex items-center gap-1.5 px-2.5 py-1" style={{ borderRadius: 9999, fontSize: 12, color: "var(--muted)", border: "1px solid var(--line)" }}><span style={{ width: 6, height: 6, borderRadius: 9999, background: dot }} />{text}</span>);
}
function PresenceInline({ pct }: { pct: number | null }) {
  const c = pct == null ? "var(--muted)" : pct >= 70 ? "var(--forest)" : pct >= 40 ? "var(--amber-ink)" : "var(--crimson)";
  const word = pct == null ? "Sensing…" : pct >= 70 ? "You're present" : pct >= 40 ? "Uncertain" : "Not recognized";
  return (<div className="flex items-center gap-2"><Activity size={14} color={c} /><span style={{ fontSize: 13, color: "var(--muted)", flex: 1 }}>{word}</span><span className="mono" style={{ fontSize: 13, color: c }}>{pct == null ? "—" : `${pct}%`}</span></div>);
}
function Row({ label, value }: { label: string; value: string }) {
  return (<div className="field flex items-center justify-between" style={{ padding: "11px 16px" }}><span className="label" style={{ fontSize: 10.5 }}>{label}</span><span style={{ fontSize: 16 }}>{value}</span></div>);
}
const PHASE_STEPS = [{ key: "nonce", label: "Requesting a one-time challenge" }, { key: "attest", label: "Reading your behavioral signature" }, { key: "sign", label: "Signing in the Secure Enclave" }, { key: "risk", label: "Scoring four fraud signals" }] as const;
function DecisionCard({ phase, decision, reason, trust }: { phase: string; decision: Decision | null; reason: string; trust: number | null }) {
  const col = decColor(decision);
  const title = decision === "allow" ? "Payment approved" : decision === "stepup" ? "One more check" : decision === "deny" ? "Payment blocked" : "Ready when you are";
  return (<div className="card" style={{ padding: 28 }}>
    <div className="flex items-start justify-between"><div className="flex-1 min-w-0" style={{ paddingRight: 16 }}>
      <AnimatePresence mode="wait"><motion.div key={(decision ?? "") + phase} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={SPRING}>
        <div className="display" style={{ fontSize: 26, color: decision ? col : "var(--ink)" }}>{phase ? "Verifying…" : title}</div>
        <p style={{ color: "var(--muted)", fontSize: 15, marginTop: 5, lineHeight: 1.45 }}>{phase ? PHASE_STEPS.find((s) => s.key === phase)?.label : decision ? reason : "Cadence scores this payment across four signals before it clears."}</p>
      </motion.div></AnimatePresence></div>
      {decision && trust != null && (<div className="text-right shrink-0"><div className="label" style={{ marginBottom: 3 }}>Trust</div><div className="display tnum" style={{ fontSize: 34, color: col }}>{Math.round(trust * 100)}</div></div>)}</div>
    {phase && (<div className="mt-6 flex flex-col gap-2.5">{PHASE_STEPS.map((s) => { const idx = PHASE_STEPS.findIndex((x) => x.key === phase), si = PHASE_STEPS.findIndex((x) => x.key === s.key); const done = si < idx, active = si === idx;
      return (<div key={s.key} className="flex items-center gap-3" style={{ opacity: done || active ? 1 : 0.32 }}>{done ? <Check size={15} color="var(--forest)" /> : active ? <Loader2 size={15} className="animate-spin" color="var(--ink)" /> : <span style={{ width: 15 }} />}<span style={{ fontSize: 14, color: active ? "var(--ink)" : "var(--muted)" }}>{s.label}</span></div>); })}</div>)}
  </div>);
}
function SignalCard({ dim, factors, active }: { dim: string; factors: Factor[]; active: boolean }) {
  return (<div className="card relative overflow-hidden" style={{ padding: "20px 20px 20px 22px", opacity: active ? 1 : 0.55 }}>
    <span style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 4, background: DIM_ACCENT[dim] }} />
    <div className="flex items-center justify-between mb-2.5"><span style={{ fontSize: 15, fontWeight: 500 }}>{dim}</span>
      {active && factors.length > 0 && <span style={{ width: 7, height: 7, borderRadius: 9999, background: factors.some((f) => f.severity === "bad") ? "var(--crimson)" : factors.some((f) => f.severity === "warn") ? "var(--amber-ink)" : "var(--forest)" }} />}</div>
    {!active || factors.length === 0 ? <p style={{ fontSize: 13, color: "var(--muted)" }}>{DIM_BLURB[dim]}</p> : (<div className="flex flex-col gap-2">{factors.map((f, i) => (<div key={i}><div style={{ fontSize: 13.5, color: sevColor(f.severity) }}>{f.label}</div><div style={{ fontSize: 12.5, color: "var(--muted)", lineHeight: 1.4 }}>{f.detail}</div></div>))}</div>)}</div>);
}
function Recovery({ recovery, onTouch, touchState, onKyc, denied }: { recovery: string[]; onTouch: () => void; touchState: string; onKyc: () => void; denied?: boolean }) {
  return (<motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
    <div className="mt-5" style={{ paddingTop: 18, borderTop: "1px solid var(--line)" }}>
      <p style={{ fontSize: 14, color: "var(--muted)", marginBottom: 12 }}>{denied ? "This doesn't look like the account owner. If it's really you:" : "Cadence isn't fully sure — one quick confirmation:"}</p>
      <div className="flex flex-col gap-2.5">
        {recovery.includes("touchid") && <button onClick={onTouch} disabled={touchState === "waiting"} className="pill-ghost flex items-center gap-3 text-left" style={{ padding: "12px 16px" }}><ScanFace size={18} color="var(--ink)" /><div className="flex-1"><div style={{ fontSize: 14.5 }}>{touchState === "waiting" ? "Waiting for the sensor…" : touchState === "failed" ? "Touch ID didn't match — try again" : "Confirm with Touch ID"}</div><div style={{ fontSize: 12, color: "var(--muted)" }}>hardware biometric on this Mac</div></div><ArrowRight size={15} color="var(--muted)" /></button>}
        {recovery.includes("kyc") && <button onClick={onKyc} className="pill-ghost flex items-center gap-3 text-left" style={{ padding: "12px 16px" }}><ShieldCheck size={18} color="var(--ink)" /><div className="flex-1"><div style={{ fontSize: 14.5 }}>Verify identity</div><div style={{ fontSize: 12, color: "var(--muted)" }}>bureau-grade check via CRS</div></div><ArrowRight size={15} color="var(--muted)" /></button>}
      </div></div></motion.div>);
}
function ChallengeBox({ sentence, onDone }: { sentence: string; onDone: () => void }) {
  const [text, setText] = useState("");
  return (<motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
    <div className="mt-5" style={{ paddingTop: 18, borderTop: "1px solid var(--line)" }}><div className="label mb-2" style={{ color: "var(--amber-ink)" }}>Type this sentence, naturally</div><div style={{ fontSize: 15.5, marginBottom: 10 }}>{sentence}</div>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} autoFocus placeholder="type here…" className="field w-full" style={{ padding: "10px 14px", fontSize: 15, resize: "none" }} />
      <button onClick={onDone} disabled={text.length < 10} className="pill mt-3" style={{ padding: "9px 20px", fontSize: 14 }}>Re-verify</button></div></motion.div>);
}
function KycBox({ kyc, setKyc, state, msg, onSubmit, onSynthetic, onReset }: { kyc: Record<string, string>; setKyc: (k: Record<string, string>) => void; state: string; msg: string; onSubmit: () => void; onSynthetic: () => void; onReset: () => void }) {
  const fields: [string, string][] = [["First name", "firstName"], ["Last name", "lastName"], ["SSN", "ssn"], ["Date of birth", "dob"], ["Street", "street1"], ["City", "city"], ["State", "state"], ["ZIP", "zip"]];
  return (<motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
    <div className="mt-5" style={{ paddingTop: 18, borderTop: "1px solid var(--line)" }}><div className="label mb-1">Identity verification · CRS</div><p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>High-value transfer — we confirm the account holder against the credit bureaus.</p>
      <div className="grid grid-cols-2 gap-2">{fields.map(([label, k]) => (<input key={k} value={kyc[k]} placeholder={label} onChange={(e) => setKyc({ ...kyc, [k]: e.target.value })} className="field" style={{ padding: "9px 12px", fontSize: 13.5 }} />))}</div>
      {state === "failed" && <div style={{ fontSize: 12.5, color: "var(--crimson)", marginTop: 8 }}>TransUnion: {msg}</div>}
      <div className="flex items-center gap-3 mt-3 flex-wrap"><button onClick={onSubmit} disabled={state === "checking"} className="pill" style={{ padding: "9px 20px", fontSize: 14 }}>{state === "checking" ? "Verifying with CRS…" : "Verify identity"}</button>
        <button onClick={onSynthetic} className="label" style={{ cursor: "pointer" }}>demo: synthetic identity</button><button onClick={onReset} className="label" style={{ cursor: "pointer" }}>reset</button></div></div></motion.div>);
}
