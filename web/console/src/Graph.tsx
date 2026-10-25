import { useEffect, useMemo, useRef, useState } from "react";

// ---- Identity Trust Graph — the hero view ----------------------------------
// A controlled radial composition: the action core at center, 12 evidence
// nodes in four tier arcs, corroboration edges with light pulses. The agent
// rail streams real Claude reasoning and the decision.

type NodeState = "lit" | "stale" | "contradicted";
type GNode = { id: string; tier: string; label: string; state: NodeState; confidence: number; detail: string; source: string };
type GEdge = { from: string; to: string; strength?: number };
type Mandate = { active: boolean; max_amount: number; scope: string; root: string; expires_at?: number };
type GraphState = {
  nodes: GNode[]; edges: GEdge[]; mandate: Mandate;
  presence_score: number; coverage: { required: string[]; lit: string[]; satisfied: boolean };
};
type AgentResult = {
  decision: "allow" | "step_up" | "deny"; reasoning: string[]; explanation: string;
  missing: string[]; challenge?: string; agent: string; transfer?: { amount?: number } | null;
};

const TIER_COLOR: Record<string, string> = {
  identity: "#5b6cff", device: "#8b5cf6", presence: "#0eb87a", money: "#e08700",
};
const TIER_LABEL: Record<string, string> = {
  identity: "Identity · CRS", device: "Device · Secure Enclave",
  presence: "Presence · live behavior", money: "Money · Capital One",
};
const TIERS = ["identity", "device", "money", "presence"]; // top, right, bottom, left

// Even ring, tier-grouped: 12 nodes every 30°, starting top-left of the identity arc.
const ANGLES = [-120, -90, -60, -30, 0, 30, 60, 90, 120, 150, 180, 210];

const FALLBACK: GraphState = {
  nodes: [
    { id: "bureau_match", tier: "identity", label: "Bureau identity", state: "stale", confidence: 0.5, detail: "awaiting verification", source: "CRS · TransUnion" },
    { id: "credit_file", tier: "identity", label: "Credit file", state: "stale", confidence: 0.5, detail: "awaiting verification", source: "CRS · TransUnion" },
    { id: "fraud_clear", tier: "identity", label: "Fraud Finder", state: "stale", confidence: 0.5, detail: "awaiting verification", source: "CRS · TransUnion" },
    { id: "device_key", tier: "device", label: "Device-bound key", state: "lit", confidence: 0.98, detail: "Secure Enclave P-256", source: "Secure Enclave" },
    { id: "network", tier: "device", label: "Network", state: "lit", confidence: 0.92, detail: "same ASN · 14 days", source: "Secure Enclave" },
    { id: "geo", tier: "device", label: "Location", state: "lit", confidence: 0.9, detail: "Berkeley, CA", source: "Secure Enclave" },
    { id: "recipient_known", tier: "money", label: "Recipient history", state: "lit", confidence: 0.88, detail: "6 prior transfers", source: "Capital One · Nessie" },
    { id: "amount_normal", tier: "money", label: "Amount pattern", state: "lit", confidence: 0.86, detail: "within band", source: "Capital One · Nessie" },
    { id: "velocity_normal", tier: "money", label: "Velocity", state: "lit", confidence: 0.94, detail: "normal cadence", source: "Capital One · Nessie" },
    { id: "keystroke", tier: "presence", label: "Keystroke dynamics", state: "lit", confidence: 0.94, detail: "matches profile", source: "Cadence daemon" },
    { id: "pointer", tier: "presence", label: "Pointer dynamics", state: "lit", confidence: 0.91, detail: "matches profile", source: "Cadence daemon" },
    { id: "continuity", tier: "presence", label: "Session continuity", state: "lit", confidence: 0.94, detail: "no takeover", source: "Cadence daemon" },
  ],
  edges: [
    { from: "keystroke", to: "continuity" }, { from: "pointer", to: "continuity" },
    { from: "bureau_match", to: "fraud_clear" }, { from: "bureau_match", to: "credit_file" },
    { from: "device_key", to: "geo" }, { from: "device_key", to: "network" },
    { from: "recipient_known", to: "amount_normal" }, { from: "continuity", to: "device_key" },
    { from: "fraud_clear", to: "recipient_known" },
  ],
  mandate: { active: true, max_amount: 2500, scope: "known payees", root: "Margaret Okafor" },
  presence_score: 0.94,
  coverage: { required: [], lit: [], satisfied: true },
};

const CX = 380, CY = 330, R = 232, VB = "0 0 760 660";
function pos(i: number) {
  const a = (ANGLES[i] * Math.PI) / 180;
  return { x: CX + R * Math.cos(a), y: CY + R * Math.sin(a) };
}

function stateColor(n: GNode) {
  if (n.state === "contradicted") return "#e0354b";
  if (n.state === "stale") return "rgba(12,14,29,0.3)";
  return TIER_COLOR[n.tier];
}

export default function GraphView() {
  const [graph, setGraph] = useState<GraphState>(FALLBACK);
  const [live, setLive] = useState(false);
  const [amount, setAmount] = useState("6000");
  const [recipient, setRecipient] = useState("november rent");
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<string[]>([]);
  const [result, setResult] = useState<AgentResult | null>(null);
  const timers = useRef<number[]>([]);

  useEffect(() => {
    let ok = true;
    const tick = () =>
      fetch("/graph/state").then((r) => r.json()).then((g) => { if (ok && g.nodes) { setGraph(g); setLive(true); } }).catch(() => {});
    tick();
    const h = setInterval(tick, 1600);
    return () => { ok = false; clearInterval(h); timers.current.forEach(clearTimeout); };
  }, []);

  const byId = useMemo(() => Object.fromEntries(graph.nodes.map((n, i) => [n.id, { ...n, ...pos(i) }])), [graph]);
  const order = graph.nodes.map((n) => n.id);

  async function authorize() {
    timers.current.forEach(clearTimeout); timers.current = [];
    setRunning(true); setSteps([]); setResult(null);
    try {
      const r = await fetch("/agent/authorize", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amount: Number(amount) || 0, recipient, memo: recipient }),
      });
      const body = await r.json();
      const res: AgentResult = { ...(body.decision || body), transfer: body.transfer ?? null };
      if (body.graph?.nodes) setGraph(body.graph);
      // stream the recorded Claude reasoning line by line
      (res.reasoning || []).forEach((s, i) =>
        timers.current.push(window.setTimeout(() => setSteps((p) => [...p, s]), 420 + i * 640)));
      timers.current.push(window.setTimeout(() => { setResult(res); setRunning(false); },
        520 + (res.reasoning?.length || 0) * 640));
    } catch {
      setSteps(["agent unreachable — is the verifier running?"]); setRunning(false);
    }
  }

  const contradicted = graph.nodes.some((n) => n.state === "contradicted");

  return (
    <div className="rise" style={{ display: "grid", gridTemplateColumns: "minmax(0,1.55fr) minmax(360px,1fr)", gap: 20, alignItems: "start" }}>
      {/* ---- graph canvas ---- */}
      <div className="card" style={{ padding: "20px 22px 10px", position: "relative", overflow: "hidden" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <div>
            <div className="display" style={{ fontSize: 19 }}>Identity Trust Graph</div>
            <div style={{ color: "var(--text-2)", fontSize: 13.5, marginTop: 2 }}>
              Live evidence of a real, authorized human — the authority behind the agent
            </div>
          </div>
          <span className="mono" style={{ fontSize: 12, color: live ? "var(--green)" : "var(--muted)" }}>
            {live ? "● live" : "○ offline preview"}
          </span>
        </div>

        <svg viewBox={VB} style={{ width: "100%", display: "block", marginTop: 4 }} role="img"
          aria-label="Identity trust graph: evidence nodes across identity, device, presence, and money tiers">
          <defs>
            <radialGradient id="coreG" cx="50%" cy="42%" r="65%">
              <stop offset="0%" stopColor={contradicted ? "#ff5d6e" : "#7d8cff"} />
              <stop offset="100%" stopColor={contradicted ? "#c22435" : "#5b6cff"} stopOpacity="0.55" />
            </radialGradient>
            <filter id="glow" x="-80%" y="-80%" width="260%" height="260%">
              <feGaussianBlur stdDeviation="5" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>

          {/* faint spokes: core -> every node */}
          {order.map((id) => {
            const n = byId[id];
            return <line key={"s" + id} x1={CX} y1={CY} x2={n.x} y2={n.y}
              stroke={n.state === "contradicted" ? "rgba(224,53,75,0.35)" : "rgba(14,18,48,0.07)"} strokeWidth="1" />;
          })}

          {/* corroboration edges as curved paths + traveling pulses when both lit */}
          {graph.edges.map((e, i) => {
            const a = byId[e.from], b = byId[e.to];
            if (!a || !b) return null;
            const mx = (a.x + b.x) / 2 + (CX - (a.x + b.x) / 2) * 0.32;
            const my = (a.y + b.y) / 2 + (CY - (a.y + b.y) / 2) * 0.32;
            const d = `M ${a.x} ${a.y} Q ${mx} ${my} ${b.x} ${b.y}`;
            const broken = a.state === "contradicted" || b.state === "contradicted";
            const liveEdge = a.state === "lit" && b.state === "lit";
            return (
              <g key={"e" + i}>
                <path id={`edge${i}`} d={d} fill="none"
                  stroke={broken ? "rgba(224,53,75,0.55)" : liveEdge ? "rgba(91,108,255,0.42)" : "rgba(14,18,48,0.12)"}
                  strokeWidth={broken ? 1.6 : 1.2}
                  strokeDasharray={broken ? "3 5" : liveEdge ? "none" : "2 6"} />
                {liveEdge && (
                  <circle r="2.6" fill="#5b6cff" filter="url(#glow)">
                    <animateMotion dur={`${2.6 + (i % 4) * 0.7}s`} repeatCount="indefinite" begin={`${(i % 5) * 0.5}s`}>
                      <mpath href={`#edge${i}`} />
                    </animateMotion>
                  </circle>
                )}
              </g>
            );
          })}

          {/* action core */}
          <g>
            <circle cx={CX} cy={CY} r="46" fill="url(#coreG)" opacity="0.9" style={{ animation: "corePulse 3.2s ease-in-out infinite" }} />
            <circle cx={CX} cy={CY} r="46" fill="none" stroke={contradicted ? "rgba(224,53,75,0.8)" : "rgba(91,108,255,0.6)"} strokeWidth="1.3" />
            <circle cx={CX} cy={CY} r="58" fill="none" stroke={contradicted ? "rgba(224,53,75,0.3)" : "rgba(91,108,255,0.3)"} strokeWidth="1" strokeDasharray="2 7" style={{ animation: "dash 3s linear infinite" }} />
            <text x={CX} y={CY - 4} textAnchor="middle" fill="#fff" fontSize="13" fontWeight="600" fontFamily="Geist, ui-sans-serif, system-ui, -apple-system, sans-serif">
              {contradicted ? "FROZEN" : "ACTION"}
            </text>
            <text x={CX} y={CY + 14} textAnchor="middle" fill="rgba(255,255,255,0.75)" fontSize="11" fontFamily="'Geist Mono', ui-monospace, SFMono-Regular, monospace">
              {contradicted ? "revoked" : graph.coverage?.satisfied ? "proven" : "gathering"}
            </text>
          </g>

          {/* evidence nodes */}
          {order.map((id) => {
            const n = byId[id];
            const c = stateColor(n);
            const above = n.y < CY;
            return (
              <g key={id}>
                {n.state === "contradicted" && (
                  <circle cx={n.x} cy={n.y} r="15" fill="none" stroke="var(--red)" strokeWidth="1.4" style={{ animation: "redThrob 1.1s ease-in-out infinite" }} />
                )}
                <circle cx={n.x} cy={n.y} r="9" fill={n.state === "lit" ? c : "transparent"}
                  stroke={c} strokeWidth="1.6" strokeDasharray={n.state === "stale" ? "2 3" : "none"}
                  filter={n.state === "lit" ? "url(#glow)" : undefined} opacity={n.state === "lit" ? 1 : 0.9} />
                <text x={n.x} y={above ? n.y - 20 : n.y + 30} textAnchor="middle" fill="var(--text)" fontSize="12.5" fontWeight="500" fontFamily="Geist, ui-sans-serif, system-ui, -apple-system, sans-serif">{n.label}</text>
                <text x={n.x} y={above ? n.y - 36 : n.y + 46} textAnchor="middle" fill="var(--muted)" fontSize="10.5" fontFamily="'Geist Mono', ui-monospace, SFMono-Regular, monospace">
                  {n.state === "lit" ? `${Math.round(n.confidence * 100)} · ${n.detail}` : n.detail}
                </text>
              </g>
            );
          })}
        </svg>

        {/* tier legend */}
        <div style={{ display: "flex", gap: 18, padding: "4px 2px 10px", flexWrap: "wrap" }}>
          {TIERS.map((t) => (
            <span key={t} style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12, color: "var(--text-2)" }}>
              <span style={{ width: 8, height: 8, borderRadius: 99, background: TIER_COLOR[t], boxShadow: `0 0 8px ${TIER_COLOR[t]}` }} />
              {TIER_LABEL[t]}
            </span>
          ))}
        </div>
      </div>

      {/* ---- agent rail ---- */}
      <div style={{ display: "grid", gap: 14 }}>
        <div className="card" style={{ padding: "16px 18px" }}>
          <div className="label">Mandate · root of trust</div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 8 }}>
            <div>
              <div className="display" style={{ fontSize: 16 }}>{graph.mandate?.root || "—"}</div>
              <div style={{ color: "var(--text-2)", fontSize: 13 }}>
                {graph.mandate?.scope} · <span className="mono">${(graph.mandate?.max_amount ?? 0).toLocaleString()}</span> autonomous · above with verified ID
              </div>
            </div>
            <span className="mono" style={{
              fontSize: 11.5, padding: "4px 11px", borderRadius: 99,
              border: `1px solid ${contradicted ? "var(--red)" : "rgba(12,159,110,0.45)"}`,
              color: contradicted ? "var(--red)" : "var(--green)",
              boxShadow: `0 0 14px ${contradicted ? "var(--glow-red)" : "rgba(12,159,110,0.15)"}`,
            }}>{contradicted ? "REVOKED" : "ACTIVE"}</span>
          </div>
          <div style={{ marginTop: 10, height: 5, borderRadius: 99, background: "rgba(14,18,48,0.08)", overflow: "hidden" }}>
            <div style={{
              width: `${Math.round((graph.presence_score ?? 0) * 100)}%`, height: "100%", borderRadius: 99,
              background: contradicted ? "linear-gradient(90deg,#e0354b,#ff8a5e)" : "linear-gradient(90deg,#0eb87a,#5b6cff)",
              transition: "width 0.9s cubic-bezier(0.22,1,0.36,1)",
            }} />
          </div>
          <div className="mono" style={{ fontSize: 11, color: "var(--muted)", marginTop: 5 }}>
            live human-presence proof · {Math.round((graph.presence_score ?? 0) * 100)}
          </div>
        </div>

        <div className="card" style={{ padding: "16px 18px" }}>
          <div className="label">Delegate to the agent</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1.4fr", gap: 10, marginTop: 10 }}>
            <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal"
              className="mono" aria-label="amount"
              style={{ background: "#fff", border: "1px solid var(--border-2)", borderRadius: 9, color: "var(--text)", padding: "9px 12px", fontSize: 14, outline: "none" }} />
            <input value={recipient} onChange={(e) => setRecipient(e.target.value)} aria-label="recipient"
              style={{ background: "#fff", border: "1px solid var(--border-2)", borderRadius: 9, color: "var(--text)", padding: "9px 12px", fontSize: 14, outline: "none", fontFamily: "inherit" }} />
          </div>
          <button className="btn-primary" disabled={running} onClick={authorize}
            style={{ width: "100%", marginTop: 12, padding: "10px 0", fontSize: 14.5 }}>
            {running ? "Agent reasoning…" : "Authorize & execute"}
          </button>
        </div>

        <div className="card" style={{ padding: "16px 18px", minHeight: 210 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <div className="label">Agent reasoning</div>
            <span className="mono" style={{ fontSize: 10.5, color: "var(--muted)" }}>claude · over the trust graph</span>
          </div>
          <div style={{ marginTop: 10, display: "grid", gap: 8 }}>
            {steps.length === 0 && !running && (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Delegate an action — the agent reasons over the graph before a dollar moves.</div>
            )}
            {steps.map((s, i) => (
              <div key={i} className="rise mono" style={{ fontSize: 12.5, color: "var(--text-2)", display: "flex", gap: 9 }}>
                <span style={{ color: "var(--accent)" }}>{String(i + 1).padStart(2, "0")}</span>
                <span>{s}</span>
              </div>
            ))}
            {running && steps.length >= 0 && (
              <div className="mono" style={{ fontSize: 12.5, color: "var(--accent)" }}>▮</div>
            )}
          </div>
          {result && (
            <div className="rise" style={{
              marginTop: 14, padding: "12px 14px", borderRadius: 11,
              border: `1px solid ${result.decision === "allow" ? "rgba(12,159,110,0.5)" : result.decision === "deny" ? "rgba(224,53,75,0.5)" : "rgba(178,107,0,0.45)"}`,
              background: result.decision === "allow" ? "rgba(12,159,110,0.06)" : result.decision === "deny" ? "rgba(224,53,75,0.05)" : "rgba(178,107,0,0.06)",
              boxShadow: `0 0 26px ${result.decision === "allow" ? "rgba(12,159,110,0.12)" : result.decision === "deny" ? "rgba(224,53,75,0.12)" : "rgba(178,107,0,0.1)"}`,
            }}>
              <div className="display" style={{
                fontSize: 15,
                color: result.decision === "allow" ? "var(--green)" : result.decision === "deny" ? "var(--red)" : "var(--amber)",
              }}>
                {result.decision === "allow" ? "Authorized — transfer executed" : result.decision === "deny" ? "Denied — money frozen" : "Step-up required"}
              </div>
              <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 4 }}>{result.explanation}</div>
              {result.transfer && (
                <div className="mono" style={{ fontSize: 11.5, color: "var(--green)", marginTop: 7 }}>
                  ✓ Capital One · Nessie transfer cleared
                </div>
              )}
              {result.challenge && (
                <div className="mono" style={{ fontSize: 11.5, color: "var(--amber)", marginTop: 7 }}>
                  → {result.challenge}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
