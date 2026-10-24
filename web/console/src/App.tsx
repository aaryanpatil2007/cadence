import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Activity, ListChecks, Users, ScrollText, ShieldCheck, Fingerprint,
  Wifi, CreditCard, CheckCircle2, Download, Bell, Cpu, Plug, TrendingUp,
  TrendingDown, Dot,
} from "lucide-react";
import {
  Alert, AuditEntry, Device, Event, Identity, Integration, Profile, Session,
  Stats, getAlerts, getAudit, getDevices, getEvents, getIdentities,
  getIntegrations, getProfiles, getStats, subscribeStream,
} from "./api";

const SPRING = { type: "spring", stiffness: 320, damping: 32 } as const;
const DIMS = [
  { key: "Presence", icon: Fingerprint }, { key: "Identity", icon: Users },
  { key: "Device", icon: Wifi }, { key: "Transaction", icon: CreditCard },
] as const;

const sev = (s: string) => s === "ok" ? "var(--green)" : s === "warn" ? "var(--amber)" : s === "bad" ? "var(--red)" : "var(--muted)";
const dcol = (d: string) => d === "allow" ? "var(--green)" : d === "stepup" ? "var(--amber)" : "var(--red)";
const fmt$ = (n: number | null) => n == null ? "—" : "$" + n.toLocaleString(undefined, { maximumFractionDigits: 0 });
const ago = (ts: number) => { const s = Math.max(0, Date.now() / 1000 - ts); return s < 60 ? `${Math.floor(s)}s` : s < 3600 ? `${Math.floor(s / 60)}m` : `${Math.floor(s / 3600)}h`; };
const agoM = (m: number) => m < 60 ? `${m}m ago` : `${Math.floor(m / 60)}h ago`;
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
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [integrations, setIntegrations] = useState<Record<string, Integration> | null>(null);

  useEffect(() => {
    const onHash = () => setRoute(location.hash || "#/overview");
    addEventListener("hashchange", onHash); return () => removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    getEvents().then(setEvents).catch(() => {}); getStats().then(setStats).catch(() => {});
    const unsub = subscribeStream(
      (e) => setEvents((p) => p.some((x) => x.id === e.id) ? p : [e, ...p].slice(0, 40)),
      (s) => setStats(s));
    return unsub;
  }, []);
  const page = route.replace("#/", "") || "overview";
  useEffect(() => {
    if (page === "identities") getIdentities().then(setIdentities).catch(() => {});
    if (page === "audit") getAudit().then(setAudit).catch(() => {});
    if (page === "sessions") getProfiles().then(setProfiles).catch(() => {});
    if (page === "alerts") getAlerts().then(setAlerts).catch(() => {});
    if (page === "devices") getDevices().then(setDevices).catch(() => {});
    if (page === "integrations") getIntegrations().then(setIntegrations).catch(() => {});
  }, [page, events.length]);

  return (
    <div className="min-h-screen flex" style={{ background: "var(--bg)" }}>
      <Sidebar page={page} alertCount={alerts.length || 3} />
      <main className="flex-1 min-w-0" style={{ padding: "26px 34px" }}>
        <AnimatePresence mode="wait">
          <motion.div key={page} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={SPRING}>
            {page === "overview" && <Overview events={events} stats={stats} />}
            {page === "sessions" && <Sessions profiles={profiles} />}
            {page === "transactions" && <Transactions events={events} />}
            {page === "alerts" && <Alerts alerts={alerts} />}
            {page === "devices" && <Devices devices={devices} />}
            {page === "identities" && <Identities items={identities} />}
            {page === "integrations" && <Integrations map={integrations} />}
            {page === "audit" && <Audit data={audit} />}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}

function Sidebar({ page, alertCount }: { page: string; alertCount: number }) {
  const nav = [
    ["overview", "Overview", Activity], ["sessions", "Behavioral sessions", Fingerprint],
    ["transactions", "Transactions", ListChecks], ["alerts", "Alerts", Bell],
    ["devices", "Devices", Cpu], ["identities", "Identities", Users],
    ["integrations", "Integrations", Plug], ["audit", "Audit log", ScrollText],
  ] as const;
  return (
    <aside style={{ width: 236, background: "var(--bg-2)", borderRight: "1px solid var(--border)" }} className="flex flex-col shrink-0">
      <div className="flex items-center gap-2.5" style={{ padding: "24px 20px 26px" }}>
        <div className="w-8 h-8 rounded-[10px] flex items-center justify-center" style={{ background: "var(--forest)" }}>
          <ShieldCheck size={17} color="#fff" strokeWidth={2} />
        </div>
        <div><div className="display" style={{ fontSize: 17, lineHeight: 1 }}>Cadence</div>
          <div className="label" style={{ fontSize: 9, marginTop: 3 }}>trust platform</div></div>
      </div>
      <nav className="flex flex-col gap-0.5 px-3">
        {nav.map(([id, label, Icon]) => {
          const active = page === id;
          return (
            <a key={id} href={`#/${id}`} className="flex items-center gap-3 px-3.5 py-2.5 rounded-lg transition"
              style={{ background: active ? "var(--elevated)" : "transparent", color: active ? "var(--text)" : "var(--text-2)" }}>
              <Icon size={16.5} strokeWidth={1.9} color={active ? "var(--forest)" : "var(--muted)"} />
              <span style={{ fontSize: 14, fontWeight: active ? 500 : 400 }}>{label}</span>
              {id === "alerts" && alertCount > 0 && (
                <span className="ml-auto mono" style={{ fontSize: 10.5, color: "#fff", background: "var(--red)", borderRadius: 9999, padding: "1px 7px" }}>{alertCount}</span>
              )}
            </a>
          );
        })}
      </nav>
      <div className="mt-auto flex items-center gap-2 px-6 py-5">
        <motion.span animate={{ opacity: [1, 0.3, 1] }} transition={{ duration: 2, repeat: Infinity }} className="w-2 h-2 rounded-full" style={{ background: "var(--green)" }} />
        <span className="label" style={{ fontSize: 10 }}>live · monitoring</span>
      </div>
    </aside>
  );
}

function PageHead({ title, sub, right }: { title: string; sub: string; right?: React.ReactNode }) {
  return (
    <div className="flex items-end justify-between mb-5">
      <div><h1 className="display" style={{ fontSize: 25 }}>{title}</h1>
        <p style={{ color: "var(--text-2)", fontSize: 14, marginTop: 2 }}>{sub}</p></div>
      {right}
    </div>
  );
}

function StatTile({ label, value, accent, trend }: { label: string; value: string; accent?: string; trend?: string }) {
  return (
    <div className="card relative overflow-hidden" style={{ padding: "18px 20px 18px 22px" }}>
      {accent && <span style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 4, background: accent }} />}
      <div className="label mb-2">{label}</div>
      <div className="flex items-end gap-2">
        <div className="display tnum" style={{ fontSize: 28 }}>{value}</div>
        {trend && <span className="flex items-center gap-0.5" style={{ fontSize: 12, color: "var(--muted)", marginBottom: 5 }}>
          <TrendingUp size={12} /> {trend}</span>}
      </div>
    </div>
  );
}

// ---------- Overview ----------
function Overview({ events, stats }: { events: Event[]; stats: Stats | null }) {
  const recent = useMemo(() => [...events].slice(0, 30).reverse(), [events]);
  return (
    <div className="flex flex-col gap-5">
      <PageHead title="Overview" sub="Every money movement, scored across four signals in real time." />
      <div className="grid grid-cols-4 gap-4 max-[900px]:grid-cols-2">
        <StatTile label="Transactions today" value={stats ? String(stats.total) : "—"} accent="var(--forest)" trend="+12%" />
        <StatTile label="Approval rate" value={stats?.approval_rate != null ? `${Math.round(stats.approval_rate * 100)}%` : "—"} accent="var(--periwinkle)" />
        <StatTile label="Fraud blocked" value={stats ? String(stats.denied) : "—"} accent="var(--candy)" />
        <StatTile label="Avg trust" value={stats?.avg_trust != null ? String(Math.round(stats.avg_trust * 100)) : "—"} accent="var(--butter)" />
      </div>
      <RiskTimeline events={recent} />
      <Stream events={events} />
    </div>
  );
}

function RiskTimeline({ events }: { events: Event[] }) {
  const W = 1000, H = 150, pad = 10, n = Math.max(events.length, 1);
  const pts = events.map((e, i) => ({ x: pad + (i / Math.max(n - 1, 1)) * (W - 2 * pad), y: pad + (1 - (e.trust ?? 0)) * (H - 2 * pad), e }));
  const line = pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const area = pts.length ? `${pad},${H - pad} ${line} ${pts[pts.length - 1].x.toFixed(1)},${H - pad}` : "";
  return (
    <div className="card p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="label">Trust over time</div>
        <div className="flex items-center gap-4">{["allow", "stepup", "deny"].map((d) => (
          <span key={d} className="flex items-center gap-1.5" style={{ fontSize: 11.5, color: "var(--text-2)" }}>
            <span className="w-2 h-2 rounded-full" style={{ background: dcol(d) }} />{d}</span>))}</div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: "100%", height: 150 }}>
        <defs><linearGradient id="tg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--forest)" stopOpacity="0.16" /><stop offset="100%" stopColor="var(--forest)" stopOpacity="0" /></linearGradient></defs>
        {[0.4, 0.7].map((th) => { const y = pad + (1 - th) * (H - 2 * pad); return <line key={th} x1={pad} x2={W - pad} y1={y} y2={y} stroke="var(--border-2)" strokeWidth="1" strokeDasharray="3 4" />; })}
        {pts.length > 1 && <polygon points={area} fill="url(#tg)" />}
        {pts.length > 1 && <polyline points={line} fill="none" stroke="var(--forest)" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />}
        {pts.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r="3" fill={dcol(p.e.decision)} stroke="var(--bg)" strokeWidth="1.5" />)}
      </svg>
      <div className="flex flex-col gap-2 mt-5">
        {DIMS.map(({ key, icon: Icon }) => (
          <div key={key} className="flex items-center gap-3">
            <div className="flex items-center gap-2" style={{ width: 118 }}><Icon size={14} color="var(--muted)" strokeWidth={1.9} /><span style={{ fontSize: 12.5, color: "var(--text-2)" }}>{key}</span></div>
            <div className="flex-1 flex gap-[3px]">{events.map((e, i) => { const s = dimSeverity(e, key); return <div key={i} className="flex-1 rounded-[2px]" style={{ height: 14, background: s === "idle" ? "var(--elevated)" : sev(s) }} />; })}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TrustPill({ trust }: { trust: number | null }) {
  const v = trust ?? 0, c = v >= 0.7 ? "var(--green)" : v >= 0.4 ? "var(--amber)" : "var(--red)";
  return (<span className="mono flex items-center gap-1.5" style={{ fontSize: 12.5, width: 52, color: c }}>
    <span className="w-6 h-1 rounded-full overflow-hidden" style={{ background: "var(--elevated)" }}><span className="block h-full rounded-full" style={{ width: `${v * 100}%`, background: c }} /></span>
    {trust == null ? "—" : Math.round(v * 100)}</span>);
}

function Stream({ events }: { events: Event[] }) {
  return (
    <div className="card p-6">
      <div className="label mb-4">Live transaction stream</div>
      <div className="flex flex-col"><AnimatePresence initial={false}>
        {events.slice(0, 11).map((e) => (
          <motion.div key={e.id} layout initial={{ backgroundColor: "rgba(0,84,61,0.07)" }} animate={{ backgroundColor: "rgba(0,0,0,0)" }} transition={{ duration: 0.9 }}
            className="flex items-center gap-4 py-2.5 px-2 rounded-lg" style={{ borderBottom: "1px solid var(--border)" }}>
            <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: dcol(e.decision) }} />
            <span style={{ fontSize: 14.5, width: 160 }} className="truncate">{e.customer ?? "—"}</span>
            <span className="mono" style={{ fontSize: 13.5, width: 80, color: "var(--text-2)" }}>{fmt$(e.amount)}</span>
            <div className="flex-1 min-w-0"><span style={{ fontSize: 13, color: "var(--text-2)" }} className="truncate">{e.reason}</span></div>
            <TrustPill trust={e.trust} />
            <span className="label" style={{ width: 52, textAlign: "right", color: dcol(e.decision) }}>{e.decision}</span>
            <span className="mono" style={{ fontSize: 11, width: 30, textAlign: "right", color: "var(--muted)" }}>{ago(e.ts)}</span>
          </motion.div>))}
      </AnimatePresence></div>
    </div>
  );
}

// ---------- Behavioral sessions (the star) ----------
function Curve({ curve, kind, w = 220, h = 44 }: { curve: number[]; kind: string; w?: number; h?: number }) {
  const n = curve.length, pad = 3;
  const pts = curve.map((v, i) => ({ x: pad + (i / Math.max(n - 1, 1)) * (w - 2 * pad), y: pad + (1 - v) * (h - 2 * pad) }));
  const line = pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const col = kind === "verified" ? "var(--forest)" : kind === "flagged" ? "var(--red)" : "var(--muted)";
  const thr = pad + (1 - 0.4) * (h - 2 * pad);
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
      <line x1={pad} x2={w - pad} y1={thr} y2={thr} stroke="var(--border-2)" strokeWidth="1" strokeDasharray="2 3" />
      <polyline points={line} fill="none" stroke={col} strokeWidth="2" strokeLinejoin="round" />
      {pts.filter((_, i) => i === n - 1).map((p, i) => <circle key={i} cx={p.x} cy={p.y} r="3" fill={col} />)}
    </svg>
  );
}

function Sessions({ profiles }: { profiles: Profile[] }) {
  return (
    <div className="flex flex-col gap-5">
      <PageHead title="Behavioral sessions" sub="How Cadence recognizes each enrolled user — and catches when someone else takes over." />
      <div className="grid grid-cols-4 gap-4 max-[900px]:grid-cols-2">
        <StatTile label="Enrolled users" value={String(profiles.length || 4)} accent="var(--forest)" />
        <StatTile label="Avg model AUC" value={profiles.length ? (profiles.reduce((a, p) => a + p.model_auc, 0) / profiles.length).toFixed(2) : "0.95"} accent="var(--periwinkle)" />
        <StatTile label="Sessions verified" value={String(profiles.reduce((a, p) => a + p.sessions.filter((s) => s.kind === "verified").length, 0) || 9)} accent="var(--candy)" />
        <StatTile label="Takeovers caught" value={String(profiles.reduce((a, p) => a + p.flagged, 0) || 3)} accent="var(--butter)" />
      </div>
      {profiles.map((p) => <ProfileCard key={p.name} p={p} />)}
    </div>
  );
}

function ProfileCard({ p }: { p: Profile }) {
  return (
    <div className="card" style={{ padding: 22 }}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full flex items-center justify-center" style={{ background: "var(--elevated)", fontSize: 14, fontWeight: 500 }}>
            {p.name.split(" ").map((w) => w[0]).join("").slice(0, 2)}</div>
          <div><div style={{ fontSize: 16, fontWeight: 500 }}>{p.name}</div>
            <div className="label" style={{ fontSize: 10 }}>{p.device}</div></div>
        </div>
        <div className="flex items-center gap-7">
          <Metric label="model AUC" value={p.model_auc.toFixed(2)} />
          <Metric label="windows trained" value={p.windows_trained.toLocaleString()} />
          <Metric label="takeovers caught" value={String(p.flagged)} color={p.flagged ? "var(--red)" : "var(--muted)"} />
        </div>
      </div>
      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(300px,1fr))" }}>
        {p.sessions.map((s) => <SessionRow key={s.id} s={s} />)}
      </div>
    </div>
  );
}

function Metric({ label, value, color }: { label: string; value: string; color?: string }) {
  return <div className="text-right"><div className="label" style={{ fontSize: 9.5 }}>{label}</div>
    <div className="mono" style={{ fontSize: 16, color: color ?? "var(--text)" }}>{value}</div></div>;
}

function SessionRow({ s }: { s: Session }) {
  const flagged = s.kind !== "verified";
  const c = flagged ? "var(--red)" : "var(--forest)";
  return (
    <div className="rounded-lg" style={{ border: "1px solid var(--border)", padding: "12px 14px" }}>
      <div className="flex items-center justify-between mb-2">
        <span className="flex items-center gap-1.5" style={{ fontSize: 12.5, color: c, fontWeight: 500 }}>
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: c }} />
          {flagged ? "Takeover flagged" : "Verified · you"}</span>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--muted)" }}>{agoM(s.minutes_ago)}</span>
      </div>
      <Curve curve={s.curve} kind={s.kind} w={272} h={42} />
      <div className="flex items-center justify-between mt-1.5">
        <span style={{ fontSize: 11.5, color: "var(--text-2)" }}>{s.note}</span>
        <span className="mono" style={{ fontSize: 11.5, color: c }}>{Math.round(s.mean * 100)}% avg</span>
      </div>
    </div>
  );
}

// ---------- Transactions ----------
function Transactions({ events }: { events: Event[] }) {
  return (
    <div className="flex flex-col gap-5">
      <PageHead title="Transactions" sub="Every scored money movement, newest first." />
      <div className="card p-2">
        <div className="flex items-center gap-4 px-4 py-3 label" style={{ borderBottom: "1px solid var(--border)" }}>
          <span style={{ width: 160 }}>Customer</span><span style={{ width: 80 }}>Amount</span><span className="flex-1">Reason</span><span style={{ width: 60 }}>Trust</span><span style={{ width: 60, textAlign: "right" }}>Decision</span></div>
        {events.map((e) => (
          <div key={e.id} className="flex items-center gap-4 px-4 py-3" style={{ borderBottom: "1px solid var(--border)" }}>
            <span style={{ fontSize: 14, width: 160 }} className="truncate">{e.customer ?? "—"}</span>
            <span className="mono" style={{ fontSize: 13.5, width: 80 }}>{fmt$(e.amount)}</span>
            <span style={{ fontSize: 13, flex: 1, color: "var(--text-2)" }} className="truncate">{e.reason}</span>
            <div style={{ width: 60 }}><TrustPill trust={e.trust} /></div>
            <span className="label" style={{ width: 60, textAlign: "right", color: dcol(e.decision) }}>{e.decision}</span></div>))}
      </div>
    </div>
  );
}

// ---------- Alerts ----------
function Alerts({ alerts }: { alerts: Alert[] }) {
  const sc = (s: string) => s === "critical" ? "var(--red)" : s === "high" ? "var(--amber-ink)" : "var(--muted)";
  const list = alerts.length ? alerts : [];
  return (
    <div className="flex flex-col gap-5">
      <PageHead title="Alerts" sub="Fraud incidents, surfaced for review — most severe first." />
      <div className="card p-2">
        {list.length === 0 && <div className="px-4 py-6" style={{ color: "var(--muted)" }}>No open incidents.</div>}
        {list.map((a, i) => (
          <div key={i} className="flex items-center gap-4 px-4 py-3.5" style={{ borderBottom: i < list.length - 1 ? "1px solid var(--border)" : "none" }}>
            <span className="label" style={{ width: 70, color: sc(a.severity) }}>{a.severity}</span>
            <div style={{ width: 200 }}><div style={{ fontSize: 14, fontWeight: 500 }}>{a.kind}</div>
              <div style={{ fontSize: 12, color: "var(--muted)" }}>{a.customer ?? "unknown"}{a.amount ? ` · ${fmt$(a.amount)}` : ""}</div></div>
            <span style={{ fontSize: 13, flex: 1, color: "var(--text-2)" }} className="truncate">{a.detail}</span>
            <span className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>{ago(a.ts)}</span>
            <span className="label px-2.5 py-1" style={{ borderRadius: 9999, color: "#fff", background: sc(a.severity), fontSize: 10 }}>{a.status}</span>
          </div>))}
      </div>
    </div>
  );
}

// ---------- Devices ----------
function Devices({ devices }: { devices: Device[] }) {
  const tc = (t: string) => t === "trusted" ? "var(--forest)" : "var(--red)";
  return (
    <div className="flex flex-col gap-5">
      <PageHead title="Device intelligence" sub="Fingerprints, networks, and hardware behind every session." />
      <div className="card p-2">
        <div className="flex items-center gap-4 px-4 py-3 label" style={{ borderBottom: "1px solid var(--border)" }}>
          <span style={{ width: 170 }}>Owner</span><span className="flex-1">Hardware</span><span style={{ width: 160 }}>Network</span><span style={{ width: 70 }}>Attempts</span><span style={{ width: 80, textAlign: "right" }}>Trust</span></div>
        {devices.map((d, i) => (
          <div key={i} className="flex items-center gap-4 px-4 py-3" style={{ borderBottom: "1px solid var(--border)" }}>
            <span style={{ fontSize: 14, width: 170 }} className="truncate">{d.owner === "unknown" ? <span style={{ color: "var(--muted)" }}>unknown</span> : d.owner}</span>
            <span style={{ fontSize: 13, flex: 1, color: "var(--text-2)" }}>{d.hardware}</span>
            <span style={{ fontSize: 13, width: 160, color: d.network.includes("datacenter") || d.network.includes("VPN") ? "var(--red)" : "var(--text-2)" }}>{d.network}</span>
            <span className="mono" style={{ fontSize: 13, width: 70 }}>{d.attempts}</span>
            <span className="label" style={{ width: 80, textAlign: "right", color: tc(d.trust) }}>{d.trust}</span></div>))}
      </div>
    </div>
  );
}

// ---------- Identities ----------
function fraudColor(level: string | null) { return level === "high" ? "var(--red)" : level === "medium" ? "var(--amber)" : "var(--green)"; }
function Identities({ items }: { items: Identity[] }) {
  return (
    <div className="flex flex-col gap-5">
      <PageHead title="Identities" sub="Every account anchored to a bureau-verified identity · CRS · TransUnion" />
      <div className="grid grid-cols-3 gap-4 max-[1000px]:grid-cols-2 max-[680px]:grid-cols-1">
        {items.map((it) => (
          <div key={it.name} className="card p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-full flex items-center justify-center" style={{ background: "var(--elevated)", fontSize: 13, fontWeight: 500 }}>{it.name.split(" ").map((w) => w[0]).join("").slice(0, 2)}</div>
                <div><div style={{ fontSize: 15, fontWeight: 500 }}>{it.name}</div><div className="label" style={{ fontSize: 9 }}>{it.mode === "live" ? "live bureau pull" : "sandbox persona"}</div></div></div>
              {it.verified ? <CheckCircle2 size={18} color="var(--green)" /> : <Dot size={18} color="var(--red)" />}</div>
            <div className="flex items-end justify-between mb-4">
              <div><div className="label mb-0.5">FICO</div><div className="display mono" style={{ fontSize: 30 }}>{it.credit_score ?? "—"}</div><div style={{ fontSize: 12, color: "var(--text-2)" }}>{it.credit_band ?? ""}</div></div>
              <div className="text-right"><div className="label mb-1.5">fraud risk</div>
                <div className="flex items-center gap-2 justify-end"><span className="w-16 h-1.5 rounded-full overflow-hidden" style={{ background: "var(--elevated)" }}><span className="block h-full rounded-full" style={{ width: `${it.fraud_risk ?? 0}%`, background: fraudColor(it.fraud_level) }} /></span>
                  <span className="mono" style={{ fontSize: 14, color: fraudColor(it.fraud_level) }}>{it.fraud_risk ?? "—"}</span></div>
                <div style={{ fontSize: 11, color: fraudColor(it.fraud_level), marginTop: 3, textAlign: "right" }}>{it.fraud_level}</div></div></div>
            <div className="flex gap-2"><Tag ok={it.verified} text={it.verified ? "IDV verified" : "IDV failed"} /><Tag ok={it.ofac_clear} text={it.ofac_clear ? "OFAC clear" : "OFAC hit"} /></div>
          </div>))}
      </div>
    </div>
  );
}
function Tag({ ok, text }: { ok: boolean; text: string }) {
  const c = ok ? "var(--green)" : "var(--red)";
  return (<span className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg" style={{ fontSize: 11.5, color: c, background: `color-mix(in srgb, ${c} 10%, transparent)` }}>
    <span className="w-1.5 h-1.5 rounded-full" style={{ background: c }} />{text}</span>);
}

// ---------- Integrations ----------
function Integrations({ map }: { map: Record<string, Integration> | null }) {
  const list = map ? Object.values(map) : [];
  const sc = (s: string) => s === "live" || s === "active" ? "var(--green)" : "var(--amber-ink)";
  return (
    <div className="flex flex-col gap-5">
      <PageHead title="Integrations" sub="The regulated data and hardware Cadence runs on." />
      <div className="grid grid-cols-2 gap-4 max-[760px]:grid-cols-1">
        {list.map((it, i) => (
          <div key={i} className="card flex items-center gap-4" style={{ padding: 22 }}>
            <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0" style={{ background: "var(--elevated)" }}><Plug size={19} color="var(--forest)" /></div>
            <div className="flex-1 min-w-0"><div style={{ fontSize: 15.5, fontWeight: 500 }}>{it.name}</div><div style={{ fontSize: 13, color: "var(--text-2)" }}>{it.detail}</div></div>
            {it.calls != null && <div className="text-right mr-2"><div className="mono" style={{ fontSize: 17 }}>{it.calls}</div><div className="label" style={{ fontSize: 9 }}>calls</div></div>}
            <span className="flex items-center gap-1.5 px-2.5 py-1" style={{ borderRadius: 9999, fontSize: 11.5, color: sc(it.status), border: `1px solid ${sc(it.status)}44` }}>
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: sc(it.status) }} />{it.status}</span>
          </div>))}
      </div>
    </div>
  );
}

// ---------- Audit ----------
function Audit({ data }: { data: { intact: boolean; length: number; entries: AuditEntry[] } | null }) {
  const entries = data ? [...data.entries].reverse() : [];
  return (
    <div className="flex flex-col gap-5">
      <PageHead title="Audit log" sub="Hash-chained, tamper-evident — every decision linked to the one before it."
        right={<button className="btn-ghost flex items-center gap-2 px-4 py-2.5" style={{ fontSize: 13.5 }} onClick={() => window.open("/console/audit", "_blank")}><Download size={15} /> Export chain</button>} />
      {data && (<div className="card flex items-center gap-3 px-5 py-3.5" style={{ borderColor: data.intact ? "color-mix(in srgb, var(--green) 40%, var(--border))" : "var(--red)" }}>
        <ShieldCheck size={18} color={data.intact ? "var(--green)" : "var(--red)"} />
        <span style={{ fontSize: 14.5 }}>{data.intact ? "Chain intact" : "Chain broken"} · {data.length} records verified</span>
        <span className="mono ml-auto" style={{ fontSize: 11.5, color: "var(--green)" }}>SHA-256</span></div>)}
      <div className="card p-2">
        {entries.map((e) => (
          <div key={e.seq} className="flex items-center gap-4 px-4 py-3" style={{ borderBottom: "1px solid var(--border)" }}>
            <span className="mono" style={{ fontSize: 12, width: 44, color: "var(--muted)" }}>#{e.seq}</span>
            <CheckCircle2 size={14} color="var(--green)" />
            <span className="label" style={{ width: 56, color: dcol(e.decision) }}>{e.decision}</span>
            <span style={{ fontSize: 13, flex: 1, color: "var(--text-2)" }} className="truncate">{e.customer ? `${e.customer} · ` : ""}{e.reason}</span>
            <span className="mono" style={{ fontSize: 11.5, color: "var(--forest)" }}>{e.hash.slice(0, 10)}…</span></div>))}
      </div>
    </div>
  );
}
