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

export type ApprovalRequest = {
  id: string;
  tool: string;
  summary: string;
  reason: string;
  risk: string;
  expires_at: number;
};

export type GuardStatus = {
  enabled: boolean;
  mode: string;
  lockdown: boolean;
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
  approvals?: ApprovalRequest[];
  guard?: GuardStatus;
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

export type SystemMetrics = {
  ok: boolean;
  ts?: number;
  cpu_percent?: number | null;
  ram?: {
    total_gb: number;
    used_gb: number;
    percent: number;
    available_gb: number;
  } | null;
  disk?: {
    path: string;
    total_gb: number;
    used_gb: number;
    percent: number;
    free_gb: number;
  } | null;
  net?: {
    bytes_sent: number;
    bytes_recv: number;
    up_mbps: number;
    down_mbps: number;
  } | null;
  error?: string | null;
};

export type UpdatesStatus = {
  ok: boolean;
  local_version?: string;
  checked_at?: number;
  channels?: {
    repo?: string;
    tag?: string;
    name?: string;
    channel?: string;
    url?: string;
    newer?: boolean;
  }[];
  error?: string | null;
  repo?: string;
};

export type VisionStatus = {
  ok: boolean;
  people_count?: number;
  people?: string[];
  last?: { event?: string; name?: string | null; ts?: number } | null;
  store?: string;
};

export type AlertItem = {
  id: string;
  kind: string;
  title: string;
  detail?: string;
  severity?: number;
  ts?: number;
  acknowledged?: boolean;
};

export type AmySettings = {
  voice_id?: string;
  voice_style?: string;
  persona_preset?: string;
  clearance_role?: string;
  clearance_label?: string;
  integrations_enabled?: string[];
};

export type SettingsOptions = {
  ok?: boolean;
  voice_presets?: { name: string; quality?: string; sample_rate?: number }[];
  voice_styles?: string[];
  persona_presets?: { id: string; label: string; blurb?: string; prompt?: string }[];
  clearance_roles?: string[];
  clearance_labels?: string[];
  integrations?: IntegrationInfo[];
  settings?: AmySettings;
  path?: string;
};

export type IntegrationInfo = {
  id: string;
  name: string;
  kind?: string;
  docs?: string;
  pack?: string;
  keys?: string[];
  configured?: Record<string, boolean>;
  ready?: boolean;
  secrets_file?: string;
};

export type ConfigField = {
  id: string;
  section: string;
  label: string;
  type:
    | "toggle"
    | "text"
    | "password"
    | "select"
    | "number"
    | "longtext"
    | "list"
    | "json"
    | string;
  path: string;
  blurb?: string;
  options?: (string | number)[];
  value?: unknown;
};

export type ConfigStudioPayload = {
  ok: boolean;
  mode?: string;
  path?: string;
  sections?: { id: string; label: string; blurb?: string }[];
  fields?: ConfigField[];
  field_count?: number;
  apps_enabled?: string[];
  local_apps?: { id: string; name?: string; base_url: string; health_path?: string }[];
  packs_available?: string[];
};

export const api = {
  health: () => req<Health>("/api/health"),
  snapshot: () => req<Snapshot>("/api/snapshot"),
  system: () => req<SystemMetrics>("/api/system"),
  toolsCatalog: (category = "") =>
    req<Record<string, unknown>>(
      `/api/tools/catalog${category ? `?category=${encodeURIComponent(category)}` : ""}`,
    ),
  updates: (check = false) =>
    req<UpdatesStatus>(`/api/updates${check ? "?check=true" : ""}`),
  visionStatus: () => req<VisionStatus>("/api/vision/status"),
  visionEnroll: (name: string, from_camera = false) =>
    req("/api/vision/enroll", {
      method: "POST",
      body: JSON.stringify({ name, from_camera }),
    }),
  alerts: (limit = 20) =>
    req<{ ok: boolean; alerts: AlertItem[] }>(`/api/alerts?limit=${limit}`),
  openHud: () => req<{ ok: boolean }>("/api/open_hud", { method: "POST" }),
  settings: () => req<SettingsOptions>("/api/settings"),
  setSettings: (body: Partial<AmySettings>) =>
    req<{ ok: boolean; settings: AmySettings }>("/api/settings", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  integrations: () =>
    req<{ ok: boolean; integrations: IntegrationInfo[] }>("/api/integrations"),
  setIntegration: (id: string, secrets: Record<string, string>) =>
    req<{ ok: boolean }>(`/api/integrations/${encodeURIComponent(id)}`, {
      method: "POST",
      body: JSON.stringify({ secrets }),
    }),
  packs: () =>
    req<{
      ok: boolean;
      packs: { id: string; name: string; path?: string; steam_root?: string }[];
      roots: string[];
      enabled?: string[];
    }>("/api/packs"),
  configStudio: () => req<ConfigStudioPayload>("/api/config"),
  saveConfigStudio: (body: {
    values?: Record<string, unknown>;
    apps_enabled?: string[];
    local_apps?: { id: string; name?: string; base_url: string; health_path?: string }[];
  }) =>
    req<ConfigStudioPayload>("/api/config", {
      method: "POST",
      body: JSON.stringify(body),
    }),
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
  approve: (id: string, approve: boolean) =>
    req<{ ok: boolean; error?: string }>("/api/approve", {
      method: "POST",
      body: JSON.stringify({ id, approve }),
    }),
  lockdown: (on: boolean) =>
    req<GuardStatus & { ok: boolean }>("/api/guard/lockdown", {
      method: "POST",
      body: JSON.stringify({ on }),
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
        Array.isArray(data.tools) ||
        Array.isArray(data.approvals)
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
