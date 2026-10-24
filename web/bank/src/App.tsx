import { useCallback, useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Landmark, Lock, ShieldCheck } from "lucide-react";

const SPRING = { type: "spring", stiffness: 260, damping: 28 } as const;
const BANK = `http://${location.hostname || "127.0.0.1"}:7900`;
const VERIFIER = `http://${location.hostname || "127.0.0.1"}:7800`;
const DAEMON = "http://127.0.0.1:7777";

type Decision = "allow" | "stepup" | "deny";
type StepState = "idle" | "active" | "ok" | "fail";

type Transfer = {
  ts: number; frm: string; to: string; amount: number; memo: string;
  decision: Decision; score: number | null; reason: string;
};

const STEPS = ["Nonce", "Behavior score", "Signature", "Policy", "Decision"];

function decisionColor(d: string | null) {
  return d === "allow" ? "var(--green)"
    : d === "stepup" ? "var(--amber)"
    : d === "deny" ? "var(--red)" : "var(--label)";
}

export default function App() {
  const [loggedIn, setLoggedIn] = useState(false);
  const [backend, setBackend] = useState<string>("mock");
  const [accounts, setAccounts] = useState<{ name: string; balance: number }[]>([]);
  const [amount, setAmount] = useState("500");
  const [memo, setMemo] = useState("");
  const [steps, setSteps] = useState<StepState[]>(Array(5).fill("idle"));
  const [stepInfo, setStepInfo] = useState<string[]>(Array(5).fill(""));
  const [decision, setDecision] = useState<Decision | null>(null);
  const [flash, setFlash] = useState<Decision | null>(null);
  const [history, setHistory] = useState<Transfer[]>([]);
  const [policy, setPolicy] = useState({ t_high: 0.7, t_low: 0.4 });
  const [busy, setBusy] = useState(false);
  const [challenge, setChallenge] = useState<string | null>(null);
  const [lastJws, setLastJws] = useState<string | null>(null);
  const [identity, setIdentity] = useState<{ name: string; verified: boolean; mode: string } | null>(null);
  const [kycOpen, setKycOpen] = useState(false);
  const [kyc, setKyc] = useState({ first_name: "KYLIA", last_name: "PAOLIMELLI", ssn: "666285642" });
  const [kycState, setKycState] = useState<"idle" | "checking" | "failed">("idle");

  const refresh = useCallback(() => {
    fetch(`${BANK}/accounts`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((j) => { setAccounts(j.accounts); setBackend(j.backend ?? "mock"); setLoggedIn(true); })
      .catch(() => {});
    fetch(`${BANK}/transfers`).then((r) => r.json())
      .then((j) => setHistory(j.transfers)).catch(() => {});
    fetch(`${VERIFIER}/policy`).then((r) => r.json()).then(setPolicy).catch(() => {});
    fetch(`${DAEMON}/status`).then((r) => r.json())
      .then((s) => fetch(`${VERIFIER}/identity/${s.device_id}`))
      .then((r) => r.json())
      .then((j) => setIdentity(j.identity ?? null))
      .catch(() => {});
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const login = async () => {
    await fetch(`${BANK}/login`, { method: "POST", credentials: "include" });
    refresh();
  };

  const setStep = (i: number, state: StepState, info = "") => {
    setSteps((s) => s.map((v, j) => (j === i ? state : v)));
    if (info) setStepInfo((s) => s.map((v, j) => (j === i ? info : v)));
  };

  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  const send = async () => {
    setBusy(true);
    setDecision(null);
    setChallenge(null);
    setSteps(Array(5).fill("idle"));
    setStepInfo(Array(5).fill(""));
    try {
      setStep(0, "active");
      const nr = await fetch(`${VERIFIER}/nonce`);
      const { nonce } = await nr.json();
      setStep(0, "ok", nonce.slice(0, 12) + "…");
      await sleep(150);

      setStep(1, "active");
      const ar = await fetch(`${DAEMON}/attest?nonce=${encodeURIComponent(nonce)}`);
      if (!ar.ok) {
        setStep(1, "fail", "no behavioral signal");
        setDecision("deny");
        setFlash("deny"); setTimeout(() => setFlash(null), 600);
        return;
      }
      const att = await ar.json();
      setLastJws(att.jws);
      setStep(1, "ok", att.payload.score.toFixed(2));
      await sleep(150);

      setStep(2, "active");
      const tr = await fetch(`${BANK}/transfer`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ to: "savings", amount: parseFloat(amount) || 0, memo, jws: att.jws }),
      });
      const res = await tr.json();
      const badSig = (res.reason || "").includes("signature")
        || (res.reason || "").includes("unknown device");
      setStep(2, badSig ? "fail" : "ok", badSig ? res.reason : "ES256 ✓");
      await sleep(150);
      setStep(3, "ok", `allow ≥ ${policy.t_high} · deny < ${policy.t_low}`);
      await sleep(150);

      const d = (res.decision as Decision) ?? "deny";
      setStep(4, d === "allow" ? "ok" : "fail", res.reason);
      setDecision(d);
      setFlash(d);
      setTimeout(() => setFlash(null), 600);
      if (d === "stepup") {
        if (res.kyc_required) {
          setKycOpen(true); // high-value: bureau-grade identity rung (CRS)
        } else {
          const sr = await fetch(`${DAEMON}/stepup/start`, { method: "POST" });
          const sj = await sr.json();
          setChallenge(sj.challenge);
        }
      }
      if (res.identity) setIdentity(res.identity);
      refresh();
    } finally {
      setBusy(false);
    }
  };

  const finishStepup = async () => {
    await fetch(`${DAEMON}/stepup/finish`, { method: "POST" });
    setChallenge(null);
    await send();
  };

  const submitKyc = async () => {
    setKycState("checking");
    try {
      const st = await fetch(`${DAEMON}/status`).then((r) => r.json());
      const r = await fetch(`${VERIFIER}/kyc`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_id: st.device_id, ...kyc }),
      });
      const j = await r.json();
      if (j.verified) {
        setKycOpen(false);
        setKycState("idle");
        await send(); // the one-time CRS exception is spent on this attempt
      } else {
        setKycState("failed");
      }
    } catch {
      setKycState("failed");
    }
  };

  if (!loggedIn) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center">
        <Landmark size={40} strokeWidth={1.2} className="text-[var(--blue)]" />
        <h1 className="text-[52px] font-semibold tracking-tight mt-4">Meridian</h1>
        <p className="text-[var(--label)] text-[18px] mt-1 mb-8">
          The demo bank that trusts behavior, not cookies.
        </p>
        <button
          onClick={login}
          className="bg-[var(--blue)] text-white rounded-full px-8 py-3 text-[17px]
            font-medium hover:brightness-110 transition"
        >
          Sign in
        </button>
        <p className="label mt-6">no password — that’s the point</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen max-w-5xl mx-auto px-8 py-8">
      {/* decision flash band */}
      <AnimatePresence>
        {flash && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 0.9 }}
            exit={{ opacity: 0 }}
            className="fixed top-0 left-0 right-0 h-1.5 z-50"
            style={{ background: decisionColor(flash), boxShadow: `0 0 32px ${decisionColor(flash)}` }}
          />
        )}
      </AnimatePresence>

      <header className="flex items-center justify-between mb-10">
        <div className="flex items-center gap-3">
          <Landmark size={22} strokeWidth={1.4} className="text-[var(--blue)]" />
          <span className="text-[19px] font-semibold tracking-tight">Meridian</span>
          {backend === "nessie" && (
            <span className="glass px-3 py-1 text-[12px] tracking-wide"
              style={{ borderRadius: 999, color: "var(--green)",
                       borderColor: "var(--green)" }}>
              LIVE · Capital One Nessie
            </span>
          )}
          {identity?.verified && (
            <span className="glass px-3 py-1 text-[12px] tracking-wide"
              style={{ borderRadius: 999, color: "var(--blue)",
                       borderColor: "var(--blue)" }}>
              Identity anchored · {identity.name} · CRS
            </span>
          )}
        </div>
        <div className="flex gap-6">
          {accounts.map((a) => (
            <div key={a.name} className="text-right">
              <div className="label">{a.name}</div>
              <div className="text-[22px] font-semibold tracking-tight"
                style={{ fontVariantNumeric: "tabular-nums" }}>
                ${a.balance.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </div>
            </div>
          ))}
        </div>
      </header>

      <div className="grid grid-cols-[1fr_1fr] gap-6 items-start">
        {/* transfer card */}
        <section className="card px-8 py-8">
          <div className="label mb-5 flex items-center gap-2">
            <Lock size={13} /> Transfer
          </div>
          <div className="flex flex-col gap-3">
            <Field label="From" value="Checking" readOnly />
            <Field label="To" value="Savings" readOnly />
            <Field
              label="Amount" value={amount} prefix="$"
              onChange={setAmount}
            />
            <Field
              label="Memo" value={memo} placeholder="type naturally here…"
              onChange={setMemo}
            />
          </div>
          <button
            onClick={send}
            disabled={busy}
            className="mt-6 w-full bg-[var(--blue)] text-white rounded-2xl py-3.5
              text-[17px] font-medium disabled:opacity-40 hover:brightness-110 transition"
          >
            {busy ? "Verifying…" : "Send"}
          </button>

          <AnimatePresence>
            {kycOpen && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="overflow-hidden"
              >
                <div className="mt-5 glass px-5 py-4"
                  style={{ borderColor: "var(--blue)" }}>
                  <div className="label mb-1" style={{ color: "var(--blue)" }}>
                    High-value transfer — identity verification (CRS)
                  </div>
                  <p className="text-[14px] text-[var(--label)] mb-3">
                    Behavior alone doesn't authorize this amount. Verify the
                    account holder's identity against the credit bureaus.
                  </p>
                  <div className="flex flex-col gap-2">
                    {([["First name", "first_name"], ["Last name", "last_name"],
                       ["SSN", "ssn"]] as const).map(([label, k]) => (
                      <input key={k} value={kyc[k]}
                        onChange={(e) => setKyc({ ...kyc, [k]: e.target.value })}
                        placeholder={label}
                        className="bg-[rgba(0,0,0,0.4)] border border-[var(--border)]
                          rounded-xl px-4 py-2.5 outline-none text-[15px]" />
                    ))}
                  </div>
                  {kycState === "failed" && (
                    <div className="mt-2 text-[13px]" style={{ color: "var(--red)" }}>
                      Identity could not be verified — transfer stays blocked.
                    </div>
                  )}
                  <button onClick={submitKyc} disabled={kycState === "checking"}
                    className="mt-3 bg-[var(--blue)] text-white rounded-full px-5
                      py-2 text-[15px] font-semibold disabled:opacity-40">
                    {kycState === "checking" ? "Verifying with CRS…" : "Verify identity"}
                  </button>
                </div>
              </motion.div>
            )}
            {challenge && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="overflow-hidden"
              >
                <div className="mt-5 glass px-5 py-4"
                  style={{ borderColor: "var(--amber)" }}>
                  <div className="label mb-2" style={{ color: "var(--amber)" }}>
                    Step-up challenge — type this sentence, then confirm
                  </div>
                  <div className="text-[17px] mb-3">{challenge}</div>
                  <textarea
                    rows={2} autoFocus
                    placeholder="Type the sentence here…"
                    className="w-full bg-[rgba(0,0,0,0.4)] border border-[var(--border)]
                      rounded-xl px-4 py-2.5 outline-none text-[16px] resize-none"
                  />
                  <button
                    onClick={finishStepup}
                    className="mt-2 bg-[var(--amber)] text-black rounded-full px-5
                      py-2 text-[15px] font-semibold"
                  >
                    Re-verify
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </section>

        {/* attestation trace */}
        <section className="card px-8 py-8">
          <div className="label mb-5 flex items-center gap-2">
            <ShieldCheck size={13} /> Attestation trace
          </div>
          <div className="flex flex-col gap-1">
            {STEPS.map((name, i) => (
              <motion.div
                key={name}
                animate={{
                  opacity: steps[i] === "idle" ? 0.35 : 1,
                  x: steps[i] === "idle" ? 0 : 4,
                }}
                transition={SPRING}
                className="flex items-center gap-4 py-2.5 border-b border-[var(--border)] last:border-0"
              >
                <span
                  className="w-2.5 h-2.5 rounded-full shrink-0 transition-colors"
                  style={{
                    background:
                      steps[i] === "ok" ? "var(--green)"
                      : steps[i] === "fail" ? "var(--red)"
                      : steps[i] === "active" ? "var(--blue)"
                      : "rgba(255,255,255,0.15)",
                    boxShadow: steps[i] !== "idle"
                      ? `0 0 10px ${steps[i] === "fail" ? "var(--red)" : "var(--green)"}` : "none",
                  }}
                />
                <span className="text-[16px] w-36">{name}</span>
                <span className="mono text-[var(--label)] truncate">{stepInfo[i]}</span>
              </motion.div>
            ))}
          </div>
          <AnimatePresence mode="wait">
            {decision && (
              <motion.div
                key={decision + history.length}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={SPRING}
                className="mt-6 rounded-2xl px-5 py-4 text-center text-[20px] font-semibold tracking-tight"
                style={{
                  color: decisionColor(decision),
                  background: `color-mix(in srgb, ${decisionColor(decision)} 12%, transparent)`,
                  border: `1px solid ${decisionColor(decision)}`,
                }}
              >
                {decision === "allow" ? "Transfer approved"
                  : decision === "stepup" ? "Step-up required"
                  : "Transfer denied"}
              </motion.div>
            )}
          </AnimatePresence>
          {lastJws && (
            <details className="mt-4">
              <summary className="label cursor-pointer">raw JWS</summary>
              <div className="mono text-[var(--label)] break-all mt-2">{lastJws}</div>
            </details>
          )}
        </section>
      </div>

      {/* history */}
      <section className="card px-8 py-6 mt-6">
        <div className="label mb-4">History</div>
        <table className="w-full text-[15px]">
          <thead>
            <tr className="label text-left">
              <th className="pb-2 font-medium">Time</th>
              <th className="pb-2 font-medium">Memo</th>
              <th className="pb-2 font-medium text-right">Amount</th>
              <th className="pb-2 font-medium text-right">Score</th>
              <th className="pb-2 font-medium text-right">Decision</th>
            </tr>
          </thead>
          <tbody>
            {history.map((t, i) => (
              <tr key={i} className="border-t border-[var(--border)]">
                <td className="py-2.5 text-[var(--label)] mono">
                  {new Date(t.ts * 1000).toLocaleTimeString()}
                </td>
                <td className="py-2.5">{t.memo || "—"}</td>
                <td className="py-2.5 text-right" style={{ fontVariantNumeric: "tabular-nums" }}>
                  ${t.amount.toFixed(2)}
                </td>
                <td className="py-2.5 text-right mono">
                  {t.score != null ? t.score.toFixed(2) : "—"}
                </td>
                <td className="py-2.5 text-right font-semibold uppercase text-[12.5px] tracking-wider"
                  style={{ color: decisionColor(t.decision) }}>
                  {t.decision}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {history.length === 0 && (
          <div className="text-[var(--label)]">No transfers yet.</div>
        )}
      </section>

      <footer className="label text-center mt-8 opacity-70">
        Every transfer requires a fresh, nonce-bound, device-signed behavior attestation.
      </footer>
    </div>
  );
}

function Field({ label, value, onChange, readOnly, placeholder, prefix }: {
  label: string; value: string; onChange?: (v: string) => void;
  readOnly?: boolean; placeholder?: string; prefix?: string;
}) {
  return (
    <label className="flex items-center gap-4 bg-[rgba(255,255,255,0.03)]
      border border-[var(--border)] rounded-2xl px-5 py-3">
      <span className="label w-16 shrink-0">{label}</span>
      {prefix && <span className="text-[var(--label)]">{prefix}</span>}
      <input
        value={value}
        readOnly={readOnly}
        placeholder={placeholder}
        onChange={(e) => onChange?.(e.target.value)}
        className="bg-transparent outline-none flex-1 text-[17px]"
      />
    </label>
  );
}
