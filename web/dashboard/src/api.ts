export const DAEMON = "http://127.0.0.1:7777";
export const VERIFIER = `http://${location.hostname || "127.0.0.1"}:7800`;

export type ScoreEvent = {
  t: number;
  score: number | null;
  keys: number | null;
  pointer: number | null;
  bot_flag: boolean;
  last_input_age_s: number | null;
  ready: boolean;
};

export type Status = {
  score: number | null;
  key_backend: string;
  profile: string;
  ready: boolean;
  device_id: string;
};

export type AuditEntry = {
  ts: number;
  action: string;
  device_id: string | null;
  score: number | null;
  decision: string;
  reason: string;
};

export async function getStatus(): Promise<Status> {
  const r = await fetch(`${DAEMON}/status`);
  return r.json();
}

export async function getAudit(): Promise<AuditEntry[]> {
  const r = await fetch(`${VERIFIER}/audit`);
  const j = await r.json();
  return j.entries;
}

export async function getPolicy(): Promise<{ t_high: number; t_low: number }> {
  const r = await fetch(`${VERIFIER}/policy`);
  return r.json();
}

export function subscribeScores(onEvent: (e: ScoreEvent) => void): () => void {
  const es = new EventSource(`${DAEMON}/events`);
  es.addEventListener("score", (ev) => {
    onEvent(JSON.parse((ev as MessageEvent).data));
  });
  return () => es.close();
}
