// Served from the verifier origin — all paths are relative.
export type Factor = { dimension: string; label: string; detail: string; severity: string };
export type Event = {
  id: number; ts: number; customer: string | null; amount: number | null;
  score: number | null; trust: number | null; decision: string;
  reason: string; factors: Factor[]; hash: string;
};
export type Identity = {
  name: string; verified: boolean; ofac_clear: boolean; mode: string;
  credit_score: number | null; credit_band: string | null;
  fraud_risk: number | null; fraud_level: string | null;
};
export type Stats = {
  total: number; allowed: number; denied: number; stepup: number;
  avg_trust: number | null; approval_rate: number | null;
};
export type AuditEntry = {
  seq: number; ts: number; action: string; customer: string | null;
  amount: number | null; decision: string; reason: string;
  prev_hash: string; hash: string; valid: boolean;
};

const j = (p: string) => fetch(p).then((r) => r.json());
export const getEvents = () => j("/console/events?limit=40").then((d) => d.events as Event[]);
export const getIdentities = () => j("/console/identities").then((d) => d.identities as Identity[]);
export const getStats = () => j("/console/stats") as Promise<Stats>;
export const getAudit = () => j("/console/audit") as Promise<{ intact: boolean; length: number; entries: AuditEntry[] }>;

export function subscribeStream(onTxn: (e: Event) => void, onStats: (s: Stats) => void): () => void {
  const es = new EventSource("/console/stream");
  es.addEventListener("txn", (e) => onTxn(JSON.parse((e as MessageEvent).data)));
  es.addEventListener("stats", (e) => onStats(JSON.parse((e as MessageEvent).data)));
  return () => es.close();
}
