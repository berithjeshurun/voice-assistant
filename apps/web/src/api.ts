import type {
  AssistantSnapshot,
  AssistantState,
  ChatMessage,
  GuardStatus,
  HealthInfo,
  HiveTask,
  TurnResponse,
} from "./generated/protocol";

export type {
  ActivityChip,
  ApprovalRequest,
  AssistantState,
  ChatMessage,
  GuardStatus,
  HiveTask,
  HudCard,
} from "./generated/protocol";

export type Snapshot = AssistantSnapshot;
export type Health = HealthInfo;
export type Role = "viewer" | "user" | "admin";

// --- auth ----------------------------------------------------------------------------
// A `?token=` link is traded once for an HttpOnly session cookie; afterwards the token
// is dropped from the URL and storage so it cannot leak via history, screenshots or
// Referer. The in-memory copy keeps this page working if cookies are unavailable.

const TOKEN_KEY = "amy_token";
const SESSION_FLAG = "amy_session";
let memToken = "";

function stripTokenFromUrl(): void {
  const url = new URL(window.location.href);
  if (!url.searchParams.has("token")) return;
  url.searchParams.delete("token");
  window.history.replaceState(window.history.state, "", url.toString());
}

export function getToken(): string {
  if (memToken) return memToken;
  const q = new URLSearchParams(window.location.search).get("token");
  if (q) {
    sessionStorage.setItem(TOKEN_KEY, q);
    return q;
  }
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

export function hasSession(): boolean {
  return sessionStorage.getItem(SESSION_FLAG) === "1";
}

/** Truthy when this page can talk to the host (token or session cookie). */
export function authKey(): string {
  return getToken() || (hasSession() ? "session" : "");
}

export function setToken(token: string): void {
  memToken = token;
  sessionStorage.setItem(TOKEN_KEY, token);
}

/** Exchange the token for a session cookie; returns false when access is denied. */
export async function establishSession(): Promise<boolean> {
  const token = getToken();
  try {
    if (token) {
      const res = await fetch("/api/session", {
        method: "POST",
        headers: { "X-Amy-Token": token },
        credentials: "same-origin",
      });
      if (!res.ok) return false;
      memToken = token;
    }
    const who = await fetch("/api/whoami", { credentials: "same-origin" });
    if (!who.ok) {
      sessionStorage.removeItem(SESSION_FLAG);
      return Boolean(token);
    }
    sessionStorage.setItem(SESSION_FLAG, "1");
    sessionStorage.removeItem(TOKEN_KEY);
    stripTokenFromUrl();
    return true;
  } catch {
    return Boolean(token);
  }
}

export async function endSession(): Promise<void> {
  memToken = "";
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(SESSION_FLAG);
  await fetch("/api/session", { method: "DELETE", credentials: "same-origin" }).catch(
    () => undefined,
  );
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function apiBase(): string {
  return "";
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("X-Amy-Token", token);
  if (init?.body) headers.set("Content-Type", "application/json");
  const res = await fetch(`${apiBase()}${path}`, {
    ...init,
    headers,
    credentials: "same-origin",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = String(body?.detail ?? body?.error ?? detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, `${res.status} ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const BUSY_MESSAGE = "Amy is still working on another request — try again in a moment.";

/** Human message for a failed turn (409 busy, 504 timeout, auth). */
export function turnErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return BUSY_MESSAGE;
    if (err.status === 504) return "That took too long and was stopped.";
    if (err.status === 401) return "Session expired — reopen the link from the host.";
    if (err.status === 403) return "This device is not allowed to do that.";
  }
  const msg = err instanceof Error ? err.message : String(err);
  return msg === "busy" ? BUSY_MESSAGE : msg;
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
  whoami: () => req<{ ok: boolean; name: string; role: Role }>("/api/whoami"),
  history: (limit = 50, q = "") =>
    req<{ ok: boolean; history: ChatMessage[] }>(
      `/api/history?limit=${limit}${q ? `&q=${encodeURIComponent(q)}` : ""}`,
    ),
  turn: (text: string) =>
    req<TurnResponse>("/api/turn", {
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

// --- live socket ---------------------------------------------------------------------

export type TurnResult = { ok: boolean; reply: string; error?: string };

export type SocketEvent =
  | { kind: "snapshot"; snapshot: Snapshot; role?: Role }
  | { kind: "turn_result"; result: TurnResult }
  | { kind: "error"; error: string; command?: string }
  | { kind: "ignore" };

/** Fold one server frame into the current snapshot (server sends a snapshot, then patches). */
export function reduceSocketMessage(current: Snapshot | null, raw: unknown): SocketEvent {
  if (!raw || typeof raw !== "object") return { kind: "ignore" };
  const msg = raw as Record<string, unknown>;
  switch (msg.type) {
    case "snapshot":
      return {
        kind: "snapshot",
        snapshot: msg.data as Snapshot,
        role: msg.role as Role | undefined,
      };
    case "patch":
      if (!current || !msg.data || typeof msg.data !== "object") return { kind: "ignore" };
      return { kind: "snapshot", snapshot: { ...current, ...(msg.data as Partial<Snapshot>) } };
    case "turn_result":
      return {
        kind: "turn_result",
        result: {
          ok: Boolean(msg.ok),
          reply: String(msg.reply ?? ""),
          error: msg.error == null ? undefined : String(msg.error),
        },
      };
    case "error":
      return {
        kind: "error",
        error: String(msg.error ?? "error"),
        command: msg.command == null ? undefined : String(msg.command),
      };
    case undefined:
      // pre-v2 servers pushed bare snapshots
      return "state" in msg ? { kind: "snapshot", snapshot: msg as Snapshot } : { kind: "ignore" };
    default:
      return { kind: "ignore" };
  }
}

export type AmySocket = {
  close(): void;
  send(cmd: { type: string; text?: string; state?: AssistantState; payload?: object }): boolean;
};

export type SocketHandlers = {
  onTurnResult?: (r: TurnResult) => void;
  onError?: (error: string) => void;
  onRole?: (role: Role) => void;
  onConnection?: (connected: boolean) => void;
};

const WS_AUTH_FAILED = 4401;
const WS_THROTTLED = 4429;

export function reconnectDelay(attempt: number, code?: number): number {
  const base = code === WS_THROTTLED ? 15_000 : 500;
  return Math.min(30_000, base * 2 ** Math.min(attempt, 6)) + Math.floor(Math.random() * 250);
}

/** Live snapshot stream with patch merging and reconnect/backoff. */
export function openAmySocket(
  onSnap: (s: Snapshot) => void,
  handlers: SocketHandlers = {},
): AmySocket | null {
  if (!authKey()) return null;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  let ws: WebSocket | null = null;
  let current: Snapshot | null = null;
  let closed = false;
  let attempt = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const connect = () => {
    // Prefer the session cookie so the token never appears in a URL.
    const token = hasSession() ? "" : getToken();
    const query = token ? `?token=${encodeURIComponent(token)}` : "";
    ws = new WebSocket(`${proto}://${location.host}/ws${query}`);
    ws.onopen = () => {
      attempt = 0;
      handlers.onConnection?.(true);
    };
    ws.onmessage = (ev) => {
      let data: unknown;
      try {
        data = JSON.parse(ev.data);
      } catch {
        return;
      }
      const event = reduceSocketMessage(current, data);
      if (event.kind === "snapshot") {
        current = event.snapshot;
        if (event.role) handlers.onRole?.(event.role);
        onSnap(event.snapshot);
      } else if (event.kind === "turn_result") {
        handlers.onTurnResult?.(event.result);
      } else if (event.kind === "error") {
        handlers.onError?.(event.error);
      }
    };
    ws.onclose = (ev) => {
      handlers.onConnection?.(false);
      ws = null;
      if (closed) return;
      if (ev.code === WS_AUTH_FAILED) {
        if (hasSession() && getToken()) {
          sessionStorage.removeItem(SESSION_FLAG);
        } else {
          handlers.onError?.("Not authorized — reopen the link from the host.");
          return;
        }
      }
      timer = setTimeout(connect, reconnectDelay(attempt++, ev.code));
    };
  };

  connect();
  return {
    close() {
      closed = true;
      if (timer) clearTimeout(timer);
      ws?.close();
    },
    send(cmd) {
      if (!ws || ws.readyState !== WebSocket.OPEN) return false;
      ws.send(JSON.stringify(cmd));
      return true;
    },
  };
}
