import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Activity, ListChecks, Users, ScrollText, ShieldCheck, Fingerprint,
  Wifi, CreditCard, CheckCircle2, Dot, Download,
} from "lucide-react";
import {
  AuditEntry, Event, Identity, Stats, getAudit, getEvents, getIdentities,
  getStats, subscribeStream,
} from "./api";

const SPRING = { type: "spring", stiffness: 320, damping: 32 } as const;
const DIMS = [
  { key: "Presence", icon: Fingerprint },
  { key: "Identity", icon: Users },
  { key: "Device", icon: Wifi },
  { key: "Transaction", icon: CreditCard },
] as const;

const sev = (s: string) => s === "ok" ? "var(--green)" : s === "warn" ? "var(--amber)" : s === "bad" ? "var(--red)" : "var(--muted)";
const dcol = (d: string) => d === "allow" ? "var(--green)" : d === "stepup" ? "var(--amber)" : "var(--red)";
const fmt$ = (n: number | null) => n == null ? "—" : "$" + n.toLocaleString(undefined, { maximumFractionDigits: 0 });
const ago = (ts: number) => {
  const s = Math.max(0, Date.now() / 1000 - ts);
  return s < 60 ? `${Math.floor(s)}s` : s < 3600 ? `${Math.floor(s / 60)}m` : `${Math.floor(s / 3600)}h`;
};
function dimSeverity(e: Event, dim: string): string {
  const fs = e.factors.filter((f) => f.dimension === dim);
  if (!fs.length) return e.decision === "deny" ? "bad" : "idle";
  return fs.some((f) => f.severity === "bad") ? "bad" : fs.some((f) => f.severity === "warn") ? "warn" : "ok";
}

export default function App() {
  const [route, setRoute] = useState(location.hash || "#/overview");
  const [events, setEvents] = useState<Event[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [identities, setIdentities] = useState<Identity[]>([]);
  const [audit, setAudit] = useState<{ intact: boolean; length: number; entries: AuditEntry[] } | null>(null);

  useEffect(() => {
    const onHash = () => setRoute(location.hash || "#/overview");
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    getEvents().then(setEvents).catch(() => {});
    getStats().then(setStats).catch(() => {});
    const unsub = subscribeStream(
      (e) => setEvents((prev) => prev.some((p) => p.id === e.id) ? prev : [e, ...prev].slice(0, 40)),
      (s) => setStats(s));
    return unsub;
  }, []);

  useEffect(() => {
    if (route.startsWith("#/identities")) getIdentities().then(setIdentities).catch(() => {});
    if (route.startsWith("#/audit")) getAudit().then(setAudit).catch(() => {});
  }, [route, events.length]);

  const page = route.replace("#/", "") || "overview";

  return (
    <div className="min-h-screen flex" style={{ background: "var(--bg)" }}>
      <Sidebar page={page} />
      <main className="flex-1 min-w-0" style={{ padding: "28px 34px" }}>
        <AnimatePresence mode="wait">
          <motion.div key={page} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }} transition={SPRING}>
            {page === "overview" && <Overview events={events} stats={stats} />}
            {page === "transactions" && <Transactions events={events} />}
            {page === "identities" && <Identities items={identities} />}
            {page === "audit" && <Audit data={audit} />}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}

function Sidebar({ page }: { page: string }) {
  const nav = [
    ["overview", "Overview", Activity],
    ["transactions", "Transactions", ListChecks],
    ["identities", "Identities", Users],
    ["audit", "Audit log", ScrollText],
  ] as const;
  return (
    <aside style={{ width: 232, background: "var(--bg-2)", borderRight: "1px solid var(--border)" }}
      className="flex flex-col shrink-0">
      <div className="flex items-center gap-2.5" style={{ padding: "26px 22px 28px" }}>
        <div className="w-8 h-8 rounded-[10px] flex items-center justify-center"
          style={{ background: "linear-gradient(180deg,var(--accent),var(--accent-deep))" }}>
          <ShieldCheck size={17} color="#fff" strokeWidth={2} />
        </div>
        <div>
          <div className="display" style={{ fontSize: 17, lineHeight: 1 }}>Cadence</div>
          <div className="label" style={{ fontSize: 9, marginTop: 3 }}>trust console</div>
        </div>
      </div>
      <nav className="flex flex-col gap-1 px-3">
        {nav.map(([id, label, Icon]) => {
          const active = page === id;
          return (
            <a key={id} href={`#/${id}`}
              className="flex items-center gap-3 px-3.5 py-2.5 rounded-xl transition"
              style={{ background: active ? "var(--elevated)" : "transparent",
                       color: active ? "var(--text)" : "var(--text-2)" }}>
              <Icon size={17} strokeWidth={1.9} color={active ? "var(--accent)" : "var(--muted)"} />
              <span style={{ fontSize: 14.5, fontWeight: active ? 560 : 460 }}>{label}</span>
            </a>
          );
        })}
      </nav>
      <div className="mt-auto flex items-center gap-2 px-6 py-5">
        <motion.span animate={{ opacity: [1, 0.3, 1] }} transition={{ duration: 2, repeat: Infinity }}
          className="w-2 h-2 rounded-full" style={{ background: "var(--green)" }} />
        <span className="label" style={{ fontSize: 10 }}>live · monitoring</span>
      </div>
    </aside>
  );
}

function StatTile({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="card p-5">
      <div className="label mb-2">{label}</div>
      <div className="display mono" style={{ fontSize: 30, color: accent ?? "var(--text)" }}>{value}</div>
    </div>
  );
}

function Overview({ events, stats }: { events: Event[]; stats: Stats | null }) {
  const recent = useMemo(() => [...events].slice(0, 30).reverse(), [events]);
  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="display" style={{ fontSize: 26 }}>Overview</h1>
        <p style={{ color: "var(--text-2)", fontSize: 14.5, marginTop: 2 }}>
          Every money movement, scored across four signals in real time.</p>
      </div>
      <div className="grid grid-cols-4 gap-4 max-[900px]:grid-cols-2">
        <StatTile label="Transactions" value={stats ? String(stats.total) : "—"} />
        <StatTile label="Approval rate" value={stats?.approval_rate != null ? `${Math.round(stats.approval_rate * 100)}%` : "—"} accent="var(--green)" />
        <StatTile label="Fraud blocked" value={stats ? String(stats.denied) : "—"} accent="var(--red)" />
        <StatTile label="Avg trust" value={stats?.avg_trust != null ? `${Math.round(stats.avg_trust * 100)}` : "—"} accent="var(--accent)" />
      </div>
      <RiskTimeline events={recent} />
      <Stream events={events} />
    </div>
  );
}

function RiskTimeline({ events }: { events: Event[] }) {
  const W = 1000, H = 150, pad = 10;
  const n = Math.max(events.length, 1);
  const pts = events.map((e, i) => {
    const x = pad + (i / Math.max(n - 1, 1)) * (W - 2 * pad);
    const y = pad + (1 - (e.trust ?? 0)) * (H - 2 * pad);
    return { x, y, e };
  });
  const line = pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const area = pts.length ? `${pad},${H - pad} ${line} ${pts[pts.length - 1].x.toFixed(1)},${H - pad}` : "";
  return (
    <div className="card p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="label">Trust over time</div>
        <div className="flex items-center gap-4">
          {["allow", "stepup", "deny"].map((d) => (
            <span key={d} className="flex items-center gap-1.5" style={{ fontSize: 11.5, color: "var(--text-2)" }}>
              <span className="w-2 h-2 rounded-full" style={{ background: dcol(d) }} />{d}</span>
          ))}
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: "100%", height: 150 }}>
        <defs>
          <linearGradient id="tg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.28" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.4, 0.7].map((th) => {
          const y = pad + (1 - th) * (H - 2 * pad);
          return <line key={th} x1={pad} x2={W - pad} y1={y} y2={y}
            stroke="var(--border-2)" strokeWidth="1" strokeDasharray="3 4" />;
        })}
        {pts.length > 1 && <polygon points={area} fill="url(#tg)" />}
        {pts.length > 1 && <polyline points={line} fill="none" stroke="var(--accent)"
          strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />}
        {pts.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r="3.2" fill={dcol(p.e.decision)}
            stroke="var(--bg)" strokeWidth="1.5" />
        ))}
      </svg>
      {/* four signal lanes */}
      <div className="flex flex-col gap-2 mt-5">
        {DIMS.map(({ key, icon: Icon }) => (
          <div key={key} className="flex items-center gap-3">
            <div className="flex items-center gap-2" style={{ width: 118 }}>
              <Icon size={14} color="var(--muted)" strokeWidth={1.9} />
              <span style={{ fontSize: 12.5, color: "var(--text-2)" }}>{key}</span>
            </div>
            <div className="flex-1 flex gap-[3px]">
              {events.map((e, i) => {
                const s = dimSeverity(e, key);
                return <div key={i} className="flex-1 rounded-[2px]" style={{ height: 14,
                  background: s === "idle" ? "var(--elevated)" : sev(s),
                  opacity: s === "idle" ? 0.5 : 0.92 }} />;
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Stream({ events }: { events: Event[] }) {
  return (
    <div className="card p-6">
      <div className="label mb-4">Live transaction stream</div>
      <div className="flex flex-col">
        <AnimatePresence initial={false}>
          {events.slice(0, 12).map((e) => (
            <motion.div key={e.id} layout
              initial={{ backgroundColor: "rgba(94,158,255,0.14)" }}
              animate={{ backgroundColor: "rgba(0,0,0,0)" }}
              transition={{ duration: 0.9 }}
              className="flex items-center gap-4 py-2.5 px-2 rounded-lg"
              style={{ borderBottom: "1px solid var(--border)" }}>
              <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: dcol(e.decision) }} />
              <span style={{ fontSize: 14.5, width: 160 }} className="truncate">{e.customer ?? "—"}</span>
              <span className="mono" style={{ fontSize: 13.5, width: 80, color: "var(--text-2)" }}>{fmt$(e.amount)}</span>
              <div className="flex-1 min-w-0">
                <span style={{ fontSize: 13, color: "var(--text-2)" }} className="truncate">{e.reason}</span>
              </div>
              <TrustPill trust={e.trust} />
              <span className="label" style={{ width: 52, textAlign: "right", color: dcol(e.decision) }}>{e.decision}</span>
              <span className="mono" style={{ fontSize: 11, width: 30, textAlign: "right", color: "var(--muted)" }}>{ago(e.ts)}</span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}

function TrustPill({ trust }: { trust: number | null }) {
  const v = trust ?? 0;
  const c = v >= 0.7 ? "var(--green)" : v >= 0.4 ? "var(--amber)" : "var(--red)";
  return (
    <span className="mono flex items-center gap-1.5" style={{ fontSize: 12.5, width: 52, color: c }}>
      <span className="w-6 h-1 rounded-full overflow-hidden" style={{ background: "var(--elevated)" }}>
        <span className="block h-full rounded-full" style={{ width: `${v * 100}%`, background: c }} />
      </span>
      {trust == null ? "—" : Math.round(v * 100)}
    </span>
  );
}

function Transactions({ events }: { events: Event[] }) {
  return (
    <div className="flex flex-col gap-5">
      <h1 className="display" style={{ fontSize: 26 }}>Transactions</h1>
      <div className="card p-2">
        <div className="flex items-center gap-4 px-4 py-3 label" style={{ borderBottom: "1px solid var(--border)" }}>
          <span style={{ width: 160 }}>Customer</span><span style={{ width: 80 }}>Amount</span>
          <span className="flex-1">Reason</span><span style={{ width: 60 }}>Trust</span>
          <span style={{ width: 60, textAlign: "right" }}>Decision</span>
        </div>
        {events.map((e) => (
          <div key={e.id} className="flex items-center gap-4 px-4 py-3"
            style={{ borderBottom: "1px solid var(--border)" }}>
            <span style={{ fontSize: 14, width: 160 }} className="truncate">{e.customer ?? "—"}</span>
            <span className="mono" style={{ fontSize: 13.5, width: 80 }}>{fmt$(e.amount)}</span>
            <span style={{ fontSize: 13, flex: 1, color: "var(--text-2)" }} className="truncate">{e.reason}</span>
            <div style={{ width: 60 }}><TrustPill trust={e.trust} /></div>
            <span className="label" style={{ width: 60, textAlign: "right", color: dcol(e.decision) }}>{e.decision}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function fraudColor(level: string | null) {
  return level === "high" ? "var(--red)" : level === "medium" ? "var(--amber)" : "var(--green)";
}

function Identities({ items }: { items: Identity[] }) {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="display" style={{ fontSize: 26 }}>Identities</h1>
        <p style={{ color: "var(--text-2)", fontSize: 14.5, marginTop: 2 }}>
          Every account anchored to a bureau-verified identity · <span style={{ color: "var(--accent)" }}>CRS · TransUnion</span></p>
      </div>
      <div className="grid grid-cols-3 gap-4 max-[1000px]:grid-cols-2 max-[680px]:grid-cols-1">
        {items.map((it) => (
          <div key={it.name} className="card p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-full flex items-center justify-center"
                  style={{ background: "var(--elevated)", fontSize: 13, fontWeight: 600 }}>
                  {it.name.split(" ").map((w) => w[0]).join("").slice(0, 2)}
                </div>
                <div>
                  <div style={{ fontSize: 15, fontWeight: 560 }}>{it.name}</div>
                  <div className="label" style={{ fontSize: 9 }}>{it.mode === "live" ? "live bureau pull" : "sandbox persona"}</div>
                </div>
              </div>
              {it.verified ? <CheckCircle2 size={18} color="var(--green)" />
                : <Dot size={18} color="var(--red)" />}
            </div>
            <div className="flex items-end justify-between mb-4">
              <div>
                <div className="label mb-0.5">FICO</div>
                <div className="display mono" style={{ fontSize: 30 }}>{it.credit_score ?? "—"}</div>
                <div style={{ fontSize: 12, color: "var(--text-2)" }}>{it.credit_band ?? ""}</div>
              </div>
              <div className="text-right">
                <div className="label mb-1.5">fraud risk</div>
                <div className="flex items-center gap-2 justify-end">
                  <span className="w-16 h-1.5 rounded-full overflow-hidden" style={{ background: "var(--elevated)" }}>
                    <span className="block h-full rounded-full" style={{ width: `${it.fraud_risk ?? 0}%`, background: fraudColor(it.fraud_level) }} />
                  </span>
                  <span className="mono" style={{ fontSize: 14, color: fraudColor(it.fraud_level) }}>{it.fraud_risk ?? "—"}</span>
                </div>
                <div style={{ fontSize: 11, color: fraudColor(it.fraud_level), marginTop: 3, textAlign: "right" }}>{it.fraud_level}</div>
              </div>
            </div>
            <div className="flex gap-2">
              <Tag ok={it.verified} text={it.verified ? "IDV verified" : "IDV failed"} />
              <Tag ok={it.ofac_clear} text={it.ofac_clear ? "OFAC clear" : "OFAC hit"} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Tag({ ok, text }: { ok: boolean; text: string }) {
  const c = ok ? "var(--green)" : "var(--red)";
  return (
    <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg"
      style={{ fontSize: 11.5, color: c, background: `color-mix(in srgb, ${c} 12%, transparent)` }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: c }} />{text}
    </span>
  );
}

function Audit({ data }: { data: { intact: boolean; length: number; entries: AuditEntry[] } | null }) {
  const entries = data ? [...data.entries].reverse() : [];
  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="display" style={{ fontSize: 26 }}>Audit log</h1>
          <p style={{ color: "var(--text-2)", fontSize: 14.5, marginTop: 2 }}>
            Hash-chained, tamper-evident — every decision linked to the one before it.</p>
        </div>
        <button className="btn-ghost flex items-center gap-2 px-4 py-2.5" style={{ fontSize: 13.5 }}
          onClick={() => window.open("/console/audit", "_blank")}>
          <Download size={15} /> Export chain
        </button>
      </div>
      {data && (
        <div className="card flex items-center gap-3 px-5 py-3.5"
          style={{ borderColor: data.intact ? "color-mix(in srgb, var(--green) 40%, var(--border))" : "var(--red)" }}>
          <ShieldCheck size={18} color={data.intact ? "var(--green)" : "var(--red)"} />
          <span style={{ fontSize: 14.5 }}>
            {data.intact ? "Chain intact" : "Chain broken"} · {data.length} records verified
          </span>
          <span className="mono ml-auto" style={{ fontSize: 11.5, color: "var(--green)" }}>SHA-256</span>
        </div>
      )}
      <div className="card p-2">
        {entries.map((e) => (
          <div key={e.seq} className="flex items-center gap-4 px-4 py-3"
            style={{ borderBottom: "1px solid var(--border)" }}>
            <span className="mono" style={{ fontSize: 12, width: 44, color: "var(--muted)" }}>#{e.seq}</span>
            <CheckCircle2 size={14} color="var(--green)" />
            <span className="label" style={{ width: 56, color: dcol(e.decision) }}>{e.decision}</span>
            <span style={{ fontSize: 13, flex: 1, color: "var(--text-2)" }} className="truncate">
              {e.customer ? `${e.customer} · ` : ""}{e.reason}</span>
            <span className="mono" style={{ fontSize: 11.5, color: "var(--accent)" }}>{e.hash.slice(0, 10)}…</span>
          </div>
        ))}
      </div>
    </div>
  );
}
