export type AssistantState =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "needs_approval"
  | "error";

export type HudCard = {
  kind: string;
  title: string;
  url: string;
  snippet: string;
};

export type ActivityChip = {
  kind: string;
  label: string;
  detail: string;
};

export type HiveTask = {
  task_id: string;
  agent_id: string;
  agent_name?: string;
  goal: string;
  status: string;
  permission_level?: string;
  max_steps?: number;
  wall_seconds?: number;
  ms?: number;
  output?: string;
  parent_id?: string | null;
  cancel_requested?: boolean;
};

export type Snapshot = {
  protocol_version: number;
  name: string;
  state: AssistantState;
  audio_level: number;
  last_user: string;
  last_assistant: string;
  detail: string;
  caption?: string;
  caption_role?: string;
  cards?: HudCard[];
  activity?: ActivityChip[];
  tools?: string[];
  tasks?: HiveTask[];
};

export type ChatMessage = { role: string; text: string; ts: number };

export type Health = {
  ok: boolean;
  name: string;
  state: AssistantState;
  voice: boolean;
  wake: boolean;
  bind: string;
  lan: boolean;
  history: ChatMessage[];
};

export function getToken(): string {
  const q = new URLSearchParams(window.location.search).get("token");
  if (q) {
    sessionStorage.setItem("amy_token", q);
    return q;
  }
  return sessionStorage.getItem("amy_token") || "";
}

export function apiBase(): string {
  return "";
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("X-Amy-Token", token);
  if (init?.body) headers.set("Content-Type", "application/json");
  const sep = path.includes("?") ? "&" : "?";
  const url = `${apiBase()}${path}${token ? `${sep}token=${encodeURIComponent(token)}` : ""}`;
  const res = await fetch(url, { ...init, headers });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<Health>("/api/health"),
  snapshot: () => req<Snapshot>("/api/snapshot"),
  cancelHiveTask: (task_id: string) =>
    req<{ ok: boolean; error?: string; task?: HiveTask }>("/api/hive/cancel", {
      method: "POST",
      body: JSON.stringify({ task_id }),
    }),
  turn: (text: string) =>
    req<{ ok: boolean; reply: string; error?: string }>("/api/turn", {
      method: "POST",
      body: JSON.stringify({ text, source: "web" }),
    }),
  wake: () => req("/api/wake", { method: "POST" }),
  barge: () => req("/api/barge", { method: "POST" }),
  setState: (state: AssistantState) =>
    req<Snapshot>("/api/state", {
      method: "POST",
      body: JSON.stringify({ type: "set_state", state }),
    }),
};

export function openAmySocket(onSnap: (s: Snapshot) => void): WebSocket | null {
  const token = getToken();
  if (!token) return null;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(
    `${proto}://${location.host}/ws?token=${encodeURIComponent(token)}`
  );
  ws.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data);
      if (
        data.state ||
        typeof data.audio_level === "number" ||
        typeof data.caption === "string" ||
        Array.isArray(data.cards) ||
        Array.isArray(data.activity) ||
        Array.isArray(data.tools)
      ) {
        onSnap(data as Snapshot);
      }
      if (data.type === "turn_result" && data.snapshot) onSnap(data.snapshot);
    } catch {
      /* ignore */
    }
  };
  return ws;
}
