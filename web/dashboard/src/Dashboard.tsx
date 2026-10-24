import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Cpu, Fingerprint, KeyRound, MousePointer2 } from "lucide-react";
import {
  AuditEntry, DAEMON, ScoreEvent, Status, getAudit, getPolicy, getStatus,
  subscribeScores,
} from "./api";

const SPRING = { type: "spring", stiffness: 260, damping: 28 } as const;

type Verdict = {
  word: string;
  color: string;
};

function verdict(
  e: ScoreEvent | null,
  policy: { t_high: number; t_low: number }
): Verdict {
  if (!e || e.score === null) return { word: "No signal", color: "var(--label)" };
  if (e.bot_flag) return { word: "Automation", color: "var(--red)" };
  if (e.score >= policy.t_high) return { word: "You", color: "var(--green)" };
  if (e.score >= policy.t_low)
    return { word: "Uncertain", color: "var(--amber)" };
  return { word: "Someone else", color: "var(--red)" };
}

function ScoreRing({ score, color }: { score: number | null; color: string }) {
  const R = 190;
  const C = 2 * Math.PI * R;
  const frac = score ?? 0;
  return (
    <svg
      width="420"
      height="420"
      viewBox="0 0 420 420"
      className="absolute inset-0 m-auto pointer-events-none"
    >
      <circle
        cx="210" cy="210" r={R} fill="none"
        stroke="rgba(10,11,12,0.08)" strokeWidth="2"
      />
      <motion.circle
        cx="210" cy="210" r={R} fill="none"
        stroke={color} strokeWidth="2.5" strokeLinecap="round"
        strokeDasharray={C}
        animate={{ strokeDashoffset: C * (1 - frac), stroke: color }}
        transition={{ type: "spring", stiffness: 60, damping: 20 }}
        transform="rotate(-90 210 210)"
        style={{ filter: `drop-shadow(0 0 12px ${color})` }}
      />
    </svg>
  );
}

function useAnimatedNumber(target: number | null): number | null {
  const [display, setDisplay] = useState<number | null>(target);
  const raf = useRef(0);
  useEffect(() => {
    if (target === null) { setDisplay(null); return; }
    setDisplay((d) => (d === null ? target : d)); // first signal: jump, no tween
    cancelAnimationFrame(raf.current);
    const step = () => {
      setDisplay((d) => {
        const cur = d ?? target;
        const next = cur + (target - cur) * 0.12;
        if (Math.abs(next - target) > 0.001) raf.current = requestAnimationFrame(step);
        return next;
      });
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
  }, [target]);
  return display;
}

function Sparkline({ history }: { history: { t: number; s: number | null }[] }) {
  const now = Date.now() / 1000;
  const pts = history
    .filter((h) => h.s !== null && now - h.t < 60)
    .map((h) => `${((1 - (now - h.t) / 60) * 100).toFixed(2)},${(
      40 - (h.s as number) * 36
    ).toFixed(2)}`);
  return (
    <svg viewBox="0 0 100 44" preserveAspectRatio="none" className="w-full h-16">
      <line x1="0" x2="100" y1="40" y2="40" stroke="var(--border)" strokeWidth="0.3" />
      {pts.length > 1 && (
        <polyline
          points={pts.join(" ")}
          fill="none" stroke="var(--blue)" strokeWidth="0.8"
          vectorEffect="non-scaling-stroke"
        />
      )}
    </svg>
  );
}

function ModalityBar({
  icon, name, value,
}: { icon: React.ReactNode; name: string; value: number | null }) {
  return (
    <div className="flex items-center gap-4">
      <span className="text-[var(--label)]">{icon}</span>
      <span className="label w-20">{name}</span>
      <div className="flex-1 h-[3px] rounded-full bg-[rgba(10,11,12,0.08)] overflow-hidden">
        <motion.div
          className="h-full rounded-full"
          style={{ background: "var(--text)" }}
          animate={{ width: `${((value ?? 0) * 100).toFixed(1)}%`, opacity: value === null ? 0.15 : 1 }}
          transition={SPRING}
        />
      </div>
      <span className="mono w-12 text-right text-[var(--label)]">
        {value === null ? "—" : value.toFixed(2)}
      </span>
    </div>
  );
}

function decisionColor(d: string) {
  return d === "allow" ? "var(--green)" : d === "stepup" ? "var(--amber)" : "var(--red)";
}

export default function Dashboard() {
  const [ev, setEv] = useState<ScoreEvent | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [attest, setAttest] = useState<Record<string, unknown> | null>(null);
  const [policy, setPolicy] = useState({ t_high: 0.7, t_low: 0.4 });
  const [history, setHistory] = useState<{ t: number; s: number | null }[]>([]);

  useEffect(() => {
    // seed the gauge immediately so there's no "No signal" flash before SSE
    fetch(`${DAEMON}/status`).then((r) => r.json()).then((s) => {
      setStatus(s);
      if (s.score != null) setEv({
        t: Date.now() / 1000, score: s.score, keys: s.modalities?.keys ?? null,
        pointer: s.modalities?.pointer ?? null, bot_flag: s.bot_flag,
        last_input_age_s: s.last_input_age_s, ready: s.ready,
        signals: s.signals,
      });
    }).catch(() => {});
    getPolicy().then(setPolicy).catch(() => {});
    const unsub = subscribeScores((e) => {
      setEv(e);
      setHistory((h) => [...h.slice(-150), { t: e.t, s: e.score }]);
    });
    const poll = setInterval(() => {
      getAudit().then(setAudit).catch(() => {});
      fetch(`${DAEMON}/last_attest`).then((r) => r.json())
        .then((j) => setAttest(j.payload ?? null)).catch(() => {});
    }, 2000);
    return () => { unsub(); clearInterval(poll); };
  }, []);

  const v = verdict(ev, policy);
  const displayed = useAnimatedNumber(ev?.score ?? null);

  return (
    <div className="min-h-screen px-10 py-8 max-w-[1500px] mx-auto">
      {/* header */}
      <header className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Fingerprint size={22} strokeWidth={1.5} />
          <span className="text-[19px] font-semibold tracking-tight">Cadence</span>
          <span className="label ml-2">Behavioral proof of identity</span>
        </div>
        <div className="flex items-center gap-3">
          <span
            className="glass px-4 py-1.5 text-[13px] flex items-center gap-2"
            style={{ borderRadius: 999 }}
          >
            <Cpu size={14} className="text-[var(--blue)]" />
            {status?.key_backend === "secure_enclave"
              ? "Secure Enclave"
              : "Device key"}
          </span>
          <a href="#/enroll" className="label hover:text-[var(--text)] transition-colors">
            Enroll
          </a>
        </div>
      </header>

      <div className="grid grid-cols-[1fr_380px] gap-6">
        {/* left column */}
        <div className="flex flex-col gap-6">
          {/* hero */}
          <section className="card relative flex flex-col items-center justify-center py-16 overflow-hidden">
            <div
              className="absolute inset-0 opacity-40 pointer-events-none"
              style={{
                background: `radial-gradient(circle at 50% 42%, ${v.color}18 0%, transparent 55%)`,
              }}
            />
            <div className="relative w-[420px] h-[420px] flex flex-col items-center justify-center">
              <ScoreRing score={ev?.score ?? null} color={v.color} />
              <div className="hero-num" style={{ color: "var(--text)" }}>
                {displayed === null ? "—" : Math.round(displayed * 100)}
              </div>
              <AnimatePresence mode="wait">
                <motion.div
                  key={v.word}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={SPRING}
                  className="text-[24px] font-semibold tracking-tight mt-2"
                  style={{ color: v.color }}
                >
                  {v.word}
                </motion.div>
              </AnimatePresence>
              <div className="label mt-3">
                confidence · last input{" "}
                {ev?.last_input_age_s != null
                  ? `${ev.last_input_age_s.toFixed(0)}s ago`
                  : "never"}
              </div>
            </div>
          </section>

          {/* sparkline + modalities */}
          <section className="card px-8 py-6">
            <div className="label mb-2">Last 60 seconds</div>
            <Sparkline history={history} />
            <div className="mt-6 flex flex-col gap-4">
              <ModalityBar
                icon={<KeyRound size={16} />} name="Keys"
                value={ev?.keys ?? null}
              />
              <ModalityBar
                icon={<MousePointer2 size={16} />} name="Pointer"
                value={ev?.pointer ?? null}
              />
            </div>
            <div className="mt-7">
              <div className="label mb-3">Live signals — what the model actually reads</div>
              <div className="grid grid-cols-4 gap-3">
                {([
                  ["Key hold", "hold_ms", "ms"],
                  ["Key gap", "gap_ms", "ms"],
                  ["Rhythm variance", "rhythm_var", ""],
                  ["Typing rate", "typing_rate", "/s"],
                  ["Mouse speed", "mouse_speed", "px/s"],
                  ["Path curvature", "curvature", "rad"],
                  ["Submovements", "submovements", ""],
                  ["Scroll rate", "scroll_rate", "/s"],
                ] as const).map(([name, key, unit]) => (
                  <div key={key}
                    className="rounded-2xl border border-[var(--border)] px-4 py-3">
                    <div className="mono text-[17px]"
                      style={{ fontVariantNumeric: "tabular-nums" }}>
                      {ev?.signals?.[key] != null ? ev.signals[key] : "—"}
                      <span className="text-[11px] text-[var(--label)] ml-1">{unit}</span>
                    </div>
                    <div className="text-[11.5px] text-[var(--label)] mt-0.5">{name}</div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* last attestation */}
          <section className="card px-8 py-6">
            <div className="label mb-3">Last attestation</div>
            {attest ? (
              <pre className="mono text-[var(--label)] whitespace-pre-wrap break-all">
                {JSON.stringify(attest, null, 2)}
              </pre>
            ) : (
              <div className="text-[var(--label)] text-[15px]">
                None yet — send a transfer from the bank.
              </div>
            )}
          </section>
        </div>

        {/* right column: verifier audit feed */}
        <aside className="card px-6 py-6 h-fit sticky top-8">
          <div className="label mb-4">Verifier audit</div>
          <div className="feed flex flex-col gap-3 max-h-[80vh] overflow-y-auto pr-1">
            <AnimatePresence initial={false}>
              {audit.map((a, i) => (
                <motion.div
                  key={`${a.ts}-${i}`}
                  initial={i === 0 ? { opacity: 0, x: 16 } : false}
                  animate={{ opacity: 1, x: 0 }}
                  transition={SPRING}
                  className="border-b border-[var(--border)] pb-3 last:border-0"
                >
                  <div className="flex items-center justify-between">
                    <span
                      className="text-[13px] font-semibold uppercase tracking-wider"
                      style={{ color: decisionColor(a.decision) }}
                    >
                      {a.decision}
                    </span>
                    <span className="mono text-[var(--label)]">
                      {new Date(a.ts * 1000).toLocaleTimeString()}
                    </span>
                  </div>
                  <div className="text-[14px] mt-0.5">{a.action}</div>
                  <div className="mono text-[var(--label)]">{a.reason}</div>
                </motion.div>
              ))}
            </AnimatePresence>
            {audit.length === 0 && (
              <div className="text-[var(--label)] text-[15px]">
                No verifications yet.
              </div>
            )}
          </div>
        </aside>
      </div>

      <footer className="label text-center mt-10 opacity-70">
        Raw input never leaves RAM — servers only ever see a signed score.
      </footer>
    </div>
  );
}
