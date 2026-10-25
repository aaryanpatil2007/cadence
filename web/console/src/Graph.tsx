import { useEffect, useMemo, useRef, useState } from "react";

// ---- Identity Trust Graph, Swiss register -----------------------------------
// White ground, black ink, exposed rules. Nodes are squares: filled when lit,
// outlined when awaiting evidence, red when contradicted. The agent rail
// shows the policy verdict and Claude's numbered reasoning over the graph.

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

const TIERS = [
  { key: "identity", n: "01", label: "Identity", src: "CRS · TransUnion" },
  { key: "device", n: "02", label: "Device", src: "Apple Secure Enclave" },
  { key: "presence", n: "03", label: "Presence", src: "on-device behavior model" },
  { key: "money", n: "04", label: "Money", src: "Capital One · Nessie ledger" },
];

const ANGLES = [-120, -90, -60, -30, 0, 30, 60, 90, 120, 150, 180, 210];

const FALLBACK: GraphState = {
  nodes: [
    { id: "bureau_match", tier: "identity", label: "Bureau identity", state: "stale", confidence: 0.5, detail: "awaiting verification", source: "CRS · TransUnion" },
    { id: "credit_file", tier: "identity", label: "Credit file", state: "stale", confidence: 0.5, detail: "awaiting verification", source: "CRS · TransUnion" },
    { id: "fraud_clear", tier: "identity", label: "Fraud Finder", state: "stale", confidence: 0.5, detail: "awaiting verification", source: "CRS · TransUnion" },
    { id: "device_key", tier: "device", label: "Device-bound key", state: "lit", confidence: 0.98, detail: "Secure Enclave P-256", source: "Secure Enclave" },
    { id: "network", tier: "device", label: "Network", state: "lit", confidence: 0.92, detail: "same ASN, 14 days", source: "Secure Enclave" },
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

export default function GraphView() {
  const [graph, setGraph] = useState<GraphState>(FALLBACK);
  const [live, setLive] = useState(false);
  const [amount, setAmount] = useState("6000");
  const [recipient, setRecipient] = useState("november rent");
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<string[]>([]);
  const [result, setResult] = useState<AgentResult | null>(null);
  const [checking, setChecking] = useState<{ name: string; done: boolean } | null>(null);
  const timers = useRef<number[]>([]);

  useEffect(() => {
    let ok = true;
    const tick = () =>
      fetch("/graph/state").then((r) => r.json()).then((g) => { if (ok && g.nodes) { setGraph(g); setLive(true); } }).catch(() => {});
    tick();
    const h = setInterval(tick, 1600);
    // demo hook: run an identity verification visibly (overlay), then let the
    // graph poll pick up the new node states
    (window as unknown as { __verifyIdentity?: (p: string) => void }).__verifyIdentity = async (persona: string) => {
      const name = persona === "fail" ? "Kayla Brennan" : "Margaret Okafor";
      setChecking({ name, done: false });
      const t0 = Date.now();
      try {
        await fetch("/graph/identity/verify", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ persona }),
        });
      } catch { /* overlay still resolves */ }
      // let the bar be seen even when the call is fast
      window.setTimeout(() => {
        setChecking({ name, done: true });
        tick();
        window.setTimeout(() => setChecking(null), 1900);
      }, Math.max(0, 2300 - (Date.now() - t0)));
    };
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
        body: JSON.stringify({ amount: Number(amount) || 0, recipient, memo: recipient, execute: !location.hash.includes("noexec") }),
      });
      const body = await r.json();
      const res: AgentResult = { ...(body.decision || body), transfer: body.transfer ?? null };
      if (body.graph?.nodes) setGraph(body.graph);
      (res.reasoning || []).forEach((s, i) =>
        timers.current.push(window.setTimeout(() => setSteps((p) => [...p, s]), 420 + i * 640)));
      timers.current.push(window.setTimeout(() => { setResult(res); setRunning(false); },
        520 + (res.reasoning?.length || 0) * 640));
    } catch {
      setSteps(["agent unreachable. is the verifier running?"]); setRunning(false);
    }
  }

  const contradicted = graph.nodes.some((n) => n.state === "contradicted");
  const S = 9; // node half-size

  return (
    <div className="rise" style={{ display: "grid", gridTemplateColumns: "minmax(0,1.55fr) minmax(370px,1fr)", gap: 0, alignItems: "stretch", border: "1px solid #000" }}>
      {/* ---- graph canvas ---- */}
      <div style={{ padding: "22px 24px 10px", borderRight: "1px solid #000", background: "#fff" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", borderBottom: "2px solid #000", paddingBottom: 12 }}>
          <div>
            <div className="display" style={{ fontSize: 26 }}>Identity Trust Graph</div>
            <div style={{ color: "var(--text-2)", fontSize: 14, marginTop: 4 }}>
              Live evidence that a real, authorized human stands behind the agent
            </div>
          </div>
          <span className="label" style={{ fontSize: 11, color: live ? "#000" : "var(--muted)" }}>
            {live ? "live" : "offline"}
            <span style={{ display: "inline-block", width: 8, height: 8, background: live ? "var(--accent)" : "#bbb", marginLeft: 7 }} />
          </span>
        </div>

        <svg viewBox={VB} style={{ width: "100%", display: "block", marginTop: 4 }} role="img"
          aria-label="Identity trust graph: evidence nodes across identity, device, presence, and money tiers">
          {/* spokes */}
          {order.map((id) => {
            const n = byId[id];
            return <line key={"s" + id} x1={CX} y1={CY} x2={n.x} y2={n.y}
              stroke={n.state === "contradicted" ? "rgba(201,0,0,0.5)" : "rgba(0,0,0,0.12)"} strokeWidth="1" />;
          })}

          {/* corroboration edges */}
          {graph.edges.map((e, i) => {
            const a = byId[e.from], b = byId[e.to];
            if (!a || !b) return null;
            const mx = (a.x + b.x) / 2 + (CX - (a.x + b.x) / 2) * 0.32;
            const my = (a.y + b.y) / 2 + (CY - (a.y + b.y) / 2) * 0.32;
            const d = `M ${a.x} ${a.y} Q ${mx} ${my} ${b.x} ${b.y}`;
            const broken = a.state === "contradicted" || b.state === "contradicted";
            const liveEdge = a.state === "lit" && b.state === "lit";
            return (
              <path key={"e" + i} d={d} fill="none"
                stroke={broken ? "#c90000" : liveEdge ? "rgba(0,0,0,0.65)" : "rgba(0,0,0,0.18)"}
                strokeWidth={broken ? 1.6 : 1.2}
                strokeDasharray={broken ? "4 4" : liveEdge ? "none" : "2 5"} />
            );
          })}

          {/* action core: black square, red when frozen */}
          <g>
            <rect x={CX - 52} y={CY - 52} width="104" height="104"
              fill={contradicted ? "#c90000" : "#000"} />
            <text x={CX} y={CY - 2} textAnchor="middle" fill="#fff" fontSize="15" fontWeight="800"
              fontFamily="Host Grotesk, Arial, sans-serif" letterSpacing="0.08em">
              {contradicted ? "FROZEN" : "ACTION"}
            </text>
            <text x={CX} y={CY + 18} textAnchor="middle" fill="rgba(255,255,255,0.8)" fontSize="11"
              fontFamily="Host Grotesk, Arial, sans-serif">
              {contradicted ? "authority revoked" : graph.coverage?.satisfied ? "authority proven" : "gathering evidence"}
            </text>
          </g>

          {/* evidence nodes: squares */}
          {order.map((id) => {
            const n = byId[id];
            const above = n.y < CY;
            const fill = n.state === "lit" ? "#000" : n.state === "contradicted" ? "#c90000" : "#fff";
            const stroke = n.state === "contradicted" ? "#c90000" : "#000";
            return (
              <g key={id}>
                <rect x={n.x - S} y={n.y - S} width={S * 2} height={S * 2}
                  fill={fill} stroke={stroke} strokeWidth="1.6"
                  strokeDasharray={n.state === "stale" ? "3 3" : "none"}
                  style={n.state === "contradicted" ? { animation: "redBlink 1.1s step-end infinite" } : undefined} />
                <text x={n.x} y={above ? n.y - 20 : n.y + 32} textAnchor="middle" fill="#000" fontSize="13" fontWeight="700"
                  fontFamily="Host Grotesk, Arial, sans-serif">{n.label}</text>
                <text x={n.x} y={above ? n.y - 36 : n.y + 48} textAnchor="middle"
                  fill={n.state === "contradicted" ? "#c90000" : "rgba(0,0,0,0.5)"} fontSize="11"
                  fontFamily="Host Grotesk, Arial, sans-serif">
                  {n.state === "lit" ? `${Math.round(n.confidence * 100)} · ${n.detail}` : n.detail}
                </text>
              </g>
            );
          })}
        </svg>

        {checking && (
          <div style={{
            position: "absolute", inset: 0, display: "grid", placeItems: "center",
            background: "rgba(255,255,255,0.82)", zIndex: 5,
          }}>
            <div className="rise" style={{ background: "#fff", border: "2px solid #000", padding: "22px 26px", width: 420 }}>
              <div className="label" style={{ display: "flex", alignItems: "center", gap: 9 }}>
                <span style={{ width: 9, height: 9, background: "var(--accent)" }} />
                CRS · TransUnion · identity verification
              </div>
              <div className="display" style={{ fontSize: 26, marginTop: 10 }}>{checking.name}</div>
              <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 4 }}>
                TruValidate identity · credit file (FICO 9) · Fraud Finder
              </div>
              <div style={{ marginTop: 14, height: 5, background: "#f0f0f0", overflow: "hidden" }}>
                <div className={checking.done ? undefined : "vbar"} style={{
                  height: "100%", background: "#000",
                  ...(checking.done ? { width: "100%", transition: "width 0.3s linear" } : {}),
                }} />
              </div>
              <div className="mono" style={{ fontSize: 11.5, marginTop: 7, color: checking.done ? "#000" : "var(--muted)" }}>
                {checking.done ? "bureau response received · updating graph" : "querying the bureau, live"}
              </div>
            </div>
          </div>
        )}

        {/* tier index rail */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", borderTop: "2px solid #000", marginTop: 6 }}>
          {TIERS.map((t, i) => (
            <div key={t.key} style={{ padding: "10px 12px 12px", borderRight: i < 3 ? "1px solid #000" : "none" }}>
              <span className="label" style={{ fontSize: 11 }}>
                <span style={{ color: "var(--accent)", marginRight: 7 }}>{t.n}</span>{t.label}
              </span>
              <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 2 }}>{t.src}</div>
            </div>
          ))}
        </div>
      </div>

      {/* ---- agent rail ---- */}
      <div style={{ display: "flex", flexDirection: "column", background: "#fff" }}>
        <div style={{ padding: "16px 18px", borderBottom: "1px solid #000" }}>
          <div className="label">Mandate · root of trust</div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 8 }}>
            <div>
              <div className="display" style={{ fontSize: 19 }}>{graph.mandate?.root || "—"}</div>
              <div style={{ color: "var(--text-2)", fontSize: 13 }}>
                {graph.mandate?.scope} · ${(graph.mandate?.max_amount ?? 0).toLocaleString()} autonomous · more with verified ID
              </div>
            </div>
            <span className="label" style={{
              fontSize: 10.5, padding: "5px 10px",
              background: contradicted ? "var(--accent)" : "#000", color: "#fff",
            }}>{contradicted ? "REVOKED" : "ACTIVE"}</span>
          </div>
          <div style={{ marginTop: 12, height: 6, background: "#f0f0f0" }}>
            <div style={{
              width: `${Math.round((graph.presence_score ?? 0) * 100)}%`, height: "100%",
              background: contradicted ? "var(--accent)" : "#000",
              transition: "width 0.5s linear",
            }} />
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 5 }}>
            live human-presence proof · {Math.round((graph.presence_score ?? 0) * 100)}
          </div>
        </div>

        <div style={{ padding: "16px 18px", borderBottom: "1px solid #000" }}>
          <div className="label">Delegate to the agent</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1.4fr", gap: 10, marginTop: 10 }}>
            <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" aria-label="amount"
              style={{ background: "#fff", border: "1px solid #000", borderRadius: 0, color: "#000", padding: "10px 12px", fontSize: 15, outline: "none", fontFamily: "inherit" }} />
            <input value={recipient} onChange={(e) => setRecipient(e.target.value)} aria-label="recipient"
              style={{ background: "#fff", border: "1px solid #000", borderRadius: 0, color: "#000", padding: "10px 12px", fontSize: 15, outline: "none", fontFamily: "inherit" }} />
          </div>
          <button className="btn-primary" disabled={running} onClick={authorize}
            style={{ width: "100%", marginTop: 12, padding: "11px 0", fontSize: 15 }}>
            {running ? "Agent reasoning" : "Authorize and execute"}
          </button>
        </div>

        <div style={{ padding: "16px 18px", flex: 1 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <div className="label">Agent reasoning</div>
            <span style={{ fontSize: 11, color: "var(--muted)" }}>Claude, over the trust graph</span>
          </div>
          <div style={{ marginTop: 10, display: "grid", gap: 9 }}>
            {steps.length === 0 && !running && (
              <div style={{ color: "var(--muted)", fontSize: 13.5 }}>
                Delegate an action. The policy engine decides from the graph; Claude explains the verdict and names any missing evidence.
              </div>
            )}
            {steps.map((s, i) => (
              <div key={i} className="rise" style={{ fontSize: 13, color: "#000", display: "flex", gap: 10, borderTop: i ? "1px solid #e4e4e4" : "none", paddingTop: i ? 8 : 0 }}>
                <span style={{ color: "var(--accent)", fontWeight: 700, minWidth: 18 }}>{String(i + 1).padStart(2, "0")}</span>
                <span style={{ lineHeight: 1.45 }}>{s}</span>
              </div>
            ))}
            {running && <div style={{ fontSize: 13, color: "var(--accent)", fontWeight: 700 }}>▌</div>}
          </div>
          {result && (
            <div className="rise" style={{
              marginTop: 14, padding: "13px 15px",
              border: `2px solid ${result.decision === "allow" ? "#000" : "var(--accent)"}`,
              background: "#fff",
            }}>
              <div className="display" style={{
                fontSize: 16,
                color: result.decision === "allow" ? "#000" : "var(--accent)",
              }}>
                {result.decision === "allow" ? "Authorized. Transfer executed" : result.decision === "deny" ? "Denied. Money frozen" : "Step-up required"}
              </div>
              <div style={{ fontSize: 13.5, color: "var(--text-2)", marginTop: 5, lineHeight: 1.45 }}>{result.explanation}</div>
              {result.transfer && (() => {
                const tr = result.transfer as { id?: string; before?: { name: string; balance: number }[]; after?: { name: string; balance: number }[] };
                const chk = (a?: { name: string; balance: number }[]) => a?.find((x) => x.name === "checking")?.balance;
                const b0 = chk(tr.before), b1 = chk(tr.after);
                return (
                  <div style={{ marginTop: 8 }}>
                    <div style={{ fontSize: 12.5, color: "#000", fontWeight: 700 }}>
                      ✓ Capital One Nessie transfer cleared
                    </div>
                    <div className="mono" style={{ fontSize: 11.5, color: "var(--text-2)", marginTop: 3 }}>
                      POST /transfers → 201 · id {String(tr.id || "").slice(0, 8)}
                      {b0 != null && b1 != null ? ` · checking $${b0.toLocaleString()} → $${b1.toLocaleString()}` : ""}
                    </div>
                  </div>
                );
              })()}
              {result.challenge && (
                <div style={{ fontSize: 12.5, color: "var(--accent)", marginTop: 8, fontWeight: 700 }}>
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
