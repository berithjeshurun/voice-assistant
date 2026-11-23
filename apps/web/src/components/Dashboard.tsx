import { FormEvent, lazy, Suspense, useEffect, useMemo, useState } from "react";
import AmyOrb from "./AmyOrb";
import SettingsPanel from "./SettingsPanel";
import IntegrationsPanel from "./IntegrationsPanel";
import WorkspacePanel from "./WorkspacePanel";
import Composer from "./Composer";
import FlashCards from "./FlashCards";
import RemindersPanel from "./RemindersPanel";
import {
  ActivityChip,
  api,
  AssistantState,
  ChatMessage,
  HiveTask,
  HudCard,
  LlmRouting,
  LlmStatus,
  ReminderItem,
  SystemMetrics,
  UpdatesStatus,
  VisionStatus,
  AlertItem,
} from "../api";

import "./Dashboard.css";

const ConfigStudio = lazy(() => import("./ConfigStudio"));

type Tab = "home" | "tasks" | "workspace" | "settings";
type SettingsPane = "controls" | "voice" | "integrations" | "config";
type TodoItem = { id: string; label: string; done: boolean; source: "user" | "agent" };

type Props = {
  state: AssistantState;
  audioLevel: number;
  caption: string;
  captionRole: string;
  detail: string;
  activity: ActivityChip[];
  cards: HudCard[];
  tasks: HiveTask[];
  history: ChatMessage[];
  meta: { voice: boolean; wake: boolean; lan: boolean };
  llm?: LlmStatus | null;
  reminders?: ReminderItem[];
  canEdit?: boolean;
  isAdmin?: boolean;
  busy: boolean;
  error: string;
  text: string;
  setText: (v: string) => void;
  onSubmit: (e: FormEvent) => void;
  onSendMessage: (msg: string) => void;
  onWake: () => void;
  onBarge: () => void;
};

function stateLabel(state: AssistantState): string {
  if (state === "listening") return "Listening";
  if (state === "thinking") return "Working";
  if (state === "speaking") return "Speaking";
  if (state === "needs_approval") return "Needs confirm";
  if (state === "error") return "Error";
  return "Ready";
}

function meter(pct: number | null | undefined) {
  const v = typeof pct === "number" ? Math.max(0, Math.min(100, pct)) : 0;
  return (
    <div className="dash-meter" aria-hidden>
      <div className="dash-meter__fill" style={{ width: `${v}%` }} />
    </div>
  );
}

export default function Dashboard({
  state,
  audioLevel,
  caption,
  captionRole,
  detail,
  activity,
  cards,
  tasks,
  history,
  meta,
  llm,
  reminders = [],
  canEdit = true,
  isAdmin = false,
  busy,
  error,
  text: _text,
  setText,
  onSubmit: _onSubmit,
  onSendMessage,
  onWake,
  onBarge,
}: Props) {
  void _onSubmit;
  void _text;

  const [tab, setTab] = useState<Tab>("home");
  const [llmRouting, setLlmRouting] = useState<LlmRouting | null>(null);
  const [llmBusy, setLlmBusy] = useState(false);
  const [settingsPane, setSettingsPane] = useState<SettingsPane>("controls");
  const [sys, setSys] = useState<SystemMetrics | null>(null);
  const [updates, setUpdates] = useState<UpdatesStatus | null>(null);
  const [vision, setVision] = useState<VisionStatus | null>(null);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [todos, setTodos] = useState<TodoItem[]>([]);
  const [newTodo, setNewTodo] = useState("");

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const m = await api.system();
        if (!cancelled) setSys(m);
      } catch {
        /* ignore */
      }
    };
    void tick();
    const id = setInterval(() => void tick(), 4000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (tab !== "settings" || settingsPane !== "controls") return;
    let cancelled = false;
    void api
      .llm()
      .then((r) => {
        if (!cancelled) setLlmRouting(r);
      })
      .catch(() => {
        if (!cancelled) setLlmRouting(null);
      });
    return () => {
      cancelled = true;
    };
  }, [tab, settingsPane]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [u, v, a] = await Promise.all([
          api.updates(false),
          api.visionStatus(),
          api.alerts(8),
        ]);
        if (cancelled) return;
        setUpdates(u);
        setVision(v);
        setAlerts(a.alerts || []);
      } catch {
        /* empty */
      }
    };
    void load();
    const id = setInterval(() => void load(), 12000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    setTodos((prev) => {
      const user = prev.filter((t) => t.source === "user");
      const agent: TodoItem[] = tasks.map((t) => ({
        id: `a:${t.task_id}`,
        label: `${t.agent_name || t.agent_id || "agent"}: ${(t.goal || "task").slice(0, 72)}`,
        done: t.status === "done" || t.status === "completed" || t.status === "failed",
        source: "agent",
      }));
      const seen = new Set(agent.map((a) => a.id));
      const retained = prev.filter((t) => t.source === "agent" && t.done && !seen.has(t.id));
      return [...user, ...agent, ...retained].slice(0, 40);
    });
  }, [tasks]);

  const envChip = activity.find((a) => a.kind === "env");
  const envLine = (envChip?.detail || envChip?.label || "").trim();
  const recent = useMemo(() => history.slice(-6).reverse(), [history]);
  const userTodos = todos.filter((t) => t.source === "user");
  const agentTodos = todos.filter((t) => t.source === "agent");
  const updateBadge = updates?.channels?.some((c) => c.newer);

  const addTodo = (label: string) => {
    const text = label.trim();
    if (!text) return;
    setTodos((rows) => [
      { id: `u:${Date.now()}`, label: text.slice(0, 120), done: false, source: "user" },
      ...rows,
    ]);
    setNewTodo("");
  };

  const handleSend = (raw: string) => {
    const msg = raw.trim();
    if (!msg) return;
    if (tab === "tasks") {
      if (msg.toLowerCase().startsWith("/run ")) {
        onSendMessage(msg.slice(5));
        return;
      }
      addTodo(msg);
      return;
    }
    setText(msg);
    onSendMessage(msg);
  };

  const nav: { id: Tab; label: string; badge?: boolean }[] = [
    { id: "home", label: "Home" },
    { id: "tasks", label: "Tasks" },
    { id: "workspace", label: "Workspace" },
    { id: "settings", label: "Settings", badge: updateBadge },
  ];

  return (
    <div className="dash" data-state={state}>
      <header className="dash-top">
        <div className="dash-brand">
          <span className="dash-brand__name">Amy</span>
          <span className={`dash-pill dash-pill--${state}`}>{stateLabel(state)}</span>
        </div>
        <div className="dash-flags" aria-label="Host status">
          <span data-on={meta.voice || undefined}>voice</span>
          <span data-on={meta.wake || undefined}>wake</span>
          <span>{meta.lan ? "lan" : "local"}</span>
          {llm ? (
            <span
              className="amy-model"
              data-on={llm.available && !llm.fallback ? true : undefined}
              data-fallback={llm.fallback || undefined}
              title={llm.model || "no model reachable"}
            >
              {llm.available ? llm.label : "no model"}
              {llm.fallback ? " · fallback" : ""}
            </span>
          ) : null}
        </div>
      </header>

      <nav className="dash-nav" aria-label="Dashboard">
        {nav.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`dash-nav__btn${tab === item.id ? " is-active" : ""}`}
            onClick={() => setTab(item.id)}
          >
            {item.label}
            {item.badge ? <i className="dash-nav__dot" aria-hidden /> : null}
          </button>
        ))}
      </nav>

      {envLine ? (
        <div className="dash-context" aria-live="polite">
          <span>Context</span>
          <p>{envLine}</p>
        </div>
      ) : null}

      <main className="dash-main">
        {tab === "home" ? (
          <>
            <section className="dash-hero">
              <div className="dash-orb">
                <AmyOrb state={state} audioLevel={audioLevel} compact interactive />
              </div>
              <div className="dash-now">
                <h2>Now</h2>
                {caption.trim() ? (
                  <p className={`dash-caption dash-caption--${captionRole || "speak"}`}>
                    {caption.trim().slice(0, 280)}
                  </p>
                ) : (
                  <p className="dash-empty">Say hey chloe, or type below.</p>
                )}
                {detail.trim() && detail !== caption ? (
                  <p className="dash-detail">{detail.slice(0, 140)}</p>
                ) : null}

                <div className="dash-actions">
                  <button type="button" className="dash-btn" onClick={onWake} disabled={busy}>
                    Wake
                  </button>
                  <button
                    type="button"
                    className="dash-btn dash-btn--ghost"
                    onClick={onBarge}
                    disabled={!busy && state !== "speaking" && state !== "thinking"}
                  >
                    Stop
                  </button>
                </div>

                <div className="dash-metrics">
                  {sys?.cpu_percent != null ? (
                    <div className="dash-metric">
                      <div className="dash-metric__row">
                        <span>CPU</span>
                        <span>{sys.cpu_percent.toFixed(0)}%</span>
                      </div>
                      {meter(sys.cpu_percent)}
                    </div>
                  ) : null}
                  {sys?.ram ? (
                    <div className="dash-metric">
                      <div className="dash-metric__row">
                        <span>RAM</span>
                        <span>
                          {sys.ram.used_gb}/{sys.ram.total_gb} GB
                        </span>
                      </div>
                      {meter(sys.ram.percent)}
                    </div>
                  ) : null}
                </div>
              </div>
            </section>

            {recent.length ? (
              <section className="dash-panel">
                <h2>Recent</h2>
                <ul className="dash-history">
                  {recent.map((m, i) => (
                    <li key={`${m.ts}-${i}`} data-role={m.role}>
                      <span>{m.role === "user" ? "You" : "Amy"}</span>
                      <p>{(m.text || "").slice(0, 160)}</p>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            <FlashCards
              cards={cards}
              activity={activity}
              busy={busy || state === "thinking"}
              onAsk={(prompt) => onSendMessage(prompt)}
            />
          </>
        ) : null}

        {tab === "tasks" ? (
          <section className="dash-panel">
            <div className="dash-panel__head">
              <h2>Tasks</h2>
              <button type="button" className="dash-btn dash-btn--ghost" onClick={onWake}>
                Wake
              </button>
            </div>
            <RemindersPanel reminders={reminders} canEdit={canEdit} />
            <p className="dash-hint">
              Add personal todos here. Prefix <code>/run</code> to send Amy a command.
            </p>
            <div className="dash-todo-add">
              <input
                value={newTodo}
                onChange={(e) => setNewTodo(e.target.value)}
                placeholder="New task…"
                autoComplete="off"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addTodo(newTodo);
                  }
                }}
              />
              <button type="button" className="dash-btn" onClick={() => addTodo(newTodo)}>
                Add
              </button>
            </div>
            <div className="dash-todo-grid">
              <div>
                <h3>Yours</h3>
                <ul className="dash-checklist">
                  {userTodos.map((item) => (
                    <li key={item.id}>
                      <label>
                        <input
                          type="checkbox"
                          checked={item.done}
                          onChange={(e) =>
                            setTodos((rows) =>
                              rows.map((r) =>
                                r.id === item.id ? { ...r, done: e.target.checked } : r,
                              ),
                            )
                          }
                        />
                        <span data-done={item.done || undefined}>{item.label}</span>
                      </label>
                    </li>
                  ))}
                  {userTodos.length === 0 ? <li className="dash-empty">No personal tasks.</li> : null}
                </ul>
              </div>
              <div>
                <h3>Agent</h3>
                <ul className="dash-checklist">
                  {agentTodos.map((item) => (
                    <li key={item.id}>
                      <label>
                        <input
                          type="checkbox"
                          checked={item.done}
                          onChange={(e) =>
                            setTodos((rows) =>
                              rows.map((r) =>
                                r.id === item.id ? { ...r, done: e.target.checked } : r,
                              ),
                            )
                          }
                        />
                        <span data-done={item.done || undefined}>{item.label}</span>
                      </label>
                    </li>
                  ))}
                  {agentTodos.length === 0 ? <li className="dash-empty">No agent tasks.</li> : null}
                </ul>
              </div>
            </div>
          </section>
        ) : null}
        {tab === "workspace" ? <WorkspacePanel onAskAmy={(msg) => onSendMessage(msg)} /> : null}

        {tab === "settings" ? (
          <div className="dash-settings">
            <div className="dash-seg" role="tablist" aria-label="Settings">
              {(
                [
                  ["controls", "Controls"],
                  ["voice", "Voice"],
                  ["integrations", "Integrations"],
                  ["config", "Config"],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={settingsPane === id}
                  className={settingsPane === id ? "is-active" : undefined}
                  onClick={() => setSettingsPane(id)}
                >
                  {label}
                </button>
              ))}
            </div>

            {settingsPane === "controls" ? (
              <section className="dash-panel">
                <h2>Controls</h2>
                <div className="dash-controls">
                  <button
                    type="button"
                    className="dash-btn"
                    onClick={() => void api.updates(true).then(setUpdates)}
                  >
                    Check updates
                  </button>
                  <button type="button" className="dash-btn dash-btn--ghost" onClick={onWake}>
                    Wake mic
                  </button>
                </div>
                <dl className="dash-kv">
                  <div>
                    <dt>Build</dt>
                    <dd>{updates?.local_version || "—"}</dd>
                  </div>
                  <div>
                    <dt>Vision</dt>
                    <dd>{vision ? `${vision.people_count} enrolled` : "—"}</dd>
                  </div>
                  <div>
                    <dt>CPU</dt>
                    <dd>
                      {sys?.cpu_percent != null ? `${sys.cpu_percent.toFixed(0)}%` : "—"}
                    </dd>
                  </div>
                  <div>
                    <dt>Model</dt>
                    <dd>{llm?.label || llmRouting?.label || "—"}</dd>
                  </div>
                </dl>
                {llmRouting?.enabled && (llmRouting.backends?.length ?? 0) > 0 ? (
                  <div className="dash-llm" aria-label="Model routing">
                    <h3>Model routing</h3>
                    <p className="dash-hint">
                      {llmRouting.pinned
                        ? `Pinned to ${llmRouting.pinned}.`
                        : "Automatic — first healthy backend wins."}
                    </p>
                    <div className="dash-controls">
                      <button
                        type="button"
                        className={`dash-btn${llmRouting.pinned == null ? "" : " dash-btn--ghost"}`}
                        disabled={!isAdmin || llmBusy}
                        onClick={() => {
                          setLlmBusy(true);
                          void api
                            .pinLlm(null)
                            .then(setLlmRouting)
                            .catch(() => undefined)
                            .finally(() => setLlmBusy(false));
                        }}
                      >
                        Auto
                      </button>
                      {(llmRouting.backends || []).map((b) => (
                        <button
                          key={b.name}
                          type="button"
                          className={`dash-btn${llmRouting.pinned === b.name ? "" : " dash-btn--ghost"}`}
                          disabled={!isAdmin || llmBusy}
                          title={b.healthy ? b.model : b.error || "unreachable"}
                          onClick={() => {
                            setLlmBusy(true);
                            void api
                              .pinLlm(b.name)
                              .then(setLlmRouting)
                              .catch(() => undefined)
                              .finally(() => setLlmBusy(false));
                          }}
                        >
                          {b.label || b.name}
                          {!b.healthy ? " · down" : ""}
                        </button>
                      ))}
                    </div>
                    {!isAdmin ? (
                      <p className="dash-hint">Admin device required to pin a model.</p>
                    ) : null}
                  </div>
                ) : null}
              </section>
            ) : null}
            {settingsPane === "voice" ? <SettingsPanel /> : null}
            {settingsPane === "integrations" ? <IntegrationsPanel /> : null}
            {settingsPane === "config" ? (
              <Suspense fallback={<p className="dash-empty">Loading config…</p>}>
                <ConfigStudio />
              </Suspense>
            ) : null}
          </div>
        ) : null}

        {error ? <p className="dash-err">{error}</p> : null}

        {alerts[0] ? (
          <aside className="dash-alert" role="status">
            <strong>{alerts[0].title || alerts[0].kind}</strong>
            {alerts[0].detail ? <span>{alerts[0].detail}</span> : null}
            <button
              type="button"
              aria-label="Dismiss"
              onClick={() => setAlerts((rows) => rows.slice(1))}
            >
              ×
            </button>
          </aside>
        ) : null}
      </main>

      <footer className="dash-composer">
        <Composer
          placeholder={
            tab === "tasks"
              ? "Add a task… (or /run tell Amy something)"
              : "Tell Amy what to do…"
          }
          busy={busy || state === "thinking"}
          onSend={handleSend}
          onWake={onWake}
          onStop={onBarge}
        />
      </footer>
    </div>
  );
}
