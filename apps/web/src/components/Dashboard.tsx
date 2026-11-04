import { FormEvent, lazy, Suspense, useEffect, useMemo, useState } from "react";
import AmyOrb from "./AmyOrb";
import SettingsPanel from "./SettingsPanel";
import IntegrationsPanel from "./IntegrationsPanel";
import WorkspacePanel from "./WorkspacePanel";
import Composer from "./Composer";
import FlashCards from "./FlashCards";
import {
  ActivityChip,
  api,
  AssistantState,
  ChatMessage,
  HiveTask,
  HudCard,
  SystemMetrics,
  UpdatesStatus,
  VisionStatus,
  AlertItem,
} from "../api";

import Dock from "./reactbits/Dock";
import TechText from "./reactbits/TechText";
import SplitFlapText from "./reactbits/SplitFlapText";
import DecryptedText from "./reactbits/DecryptedText";
import LaserFlow from "./reactbits/LaserFlow";
import Strands from "./reactbits/Strands";
import OrbitImages from "./reactbits/OrbitImages";
import CircularCarousel from "./reactbits/CircularCarousel";
import SwipeToast from "./reactbits/SwipeToast";
import StatusMark from "./reactbits/StatusMark";
import LatticeLoader from "./reactbits/LatticeLoader";
import FuseButton from "./reactbits/FuseButton";
import SpringCheck from "./reactbits/SpringCheck";
import HoldButton from "./reactbits/HoldButton";
import SquishSwitch from "./reactbits/SquishSwitch";
import RubberSegment from "./reactbits/RubberSegment";
import WarmTooltip from "./reactbits/WarmTooltip";

import "./Dashboard.css";

const ConfigStudio = lazy(() => import("./ConfigStudio"));

type Tab = "home" | "manual" | "gallery" | "workspace" | "settings";
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
  busy: boolean;
  error: string;
  text: string;
  setText: (v: string) => void;
  onSubmit: (e: FormEvent) => void;
  onSendMessage: (msg: string) => void;
  onWake: () => void;
  onBarge: () => void;
};

function pctBar(pct: number | null | undefined) {
  const v = typeof pct === "number" ? Math.max(0, Math.min(100, pct)) : 0;
  return (
    <div className="amy-meter" aria-hidden>
      <div className="amy-meter__fill" style={{ width: `${v}%` }} />
    </div>
  );
}

function boardWord(state: AssistantState): string {
  if (state === "listening") return "LISTEN";
  if (state === "thinking") return "WORK";
  if (state === "speaking") return "SPEAK";
  if (state === "needs_approval") return "CONFIRM";
  if (state === "error") return "ERROR";
  return "READY";
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
  history: _history,
  meta,
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
  void _history;
  void _text;

  const [tab, setTab] = useState<Tab>("home");
  const [settingsPane, setSettingsPane] = useState<SettingsPane>("controls");
  const [booting, setBooting] = useState(true);
  const [sys, setSys] = useState<SystemMetrics | null>(null);
  const [updates, setUpdates] = useState<UpdatesStatus | null>(null);
  const [vision, setVision] = useState<VisionStatus | null>(null);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [strandsOrb, setStrandsOrb] = useState(false);
  const [todos, setTodos] = useState<TodoItem[]>([]);
  const [newTodo, setNewTodo] = useState("");
  const [hilOpen, setHilOpen] = useState(false);
  const [toasts, setToasts] = useState<{ id: string; title: string; body?: string }[]>([]);

  useEffect(() => {
    const t = window.setTimeout(() => setBooting(false), 2200);
    return () => window.clearTimeout(t);
  }, []);

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
    const id = setInterval(() => void tick(), 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [u, v, a] = await Promise.all([
          api.updates(false),
          api.visionStatus(),
          api.alerts(12),
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
    const id = setInterval(() => void load(), 8000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (!alerts.length) return;
    const latest = alerts[0];
    setToasts((prev) => {
      if (prev.some((t) => t.id === latest.id)) return prev;
      return [
        { id: latest.id, title: latest.title || latest.kind, body: latest.detail },
        ...prev,
      ].slice(0, 3);
    });
  }, [alerts]);

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
      const retained = prev.filter(
        (t) => t.source === "agent" && t.done && !seen.has(t.id),
      );
      return [...user, ...agent, ...retained].slice(0, 40);
    });
  }, [tasks]);

  const envChip = activity.find((a) => a.kind === "env");
  const envLine = (envChip?.detail || envChip?.label || "").trim();

  /** Real media only — URLs from tool cards that look like images. */
  const galleryImages = useMemo(() => {
    return cards
      .map((c) => c.url)
      .filter((u): u is string => {
        if (!u || !/^https?:/i.test(u)) return false;
        return /\.(png|jpe?g|gif|webp|avif)(\?|$)/i.test(u) || /images\.|/i.test(u);
      })
      .slice(0, 12);
  }, [cards]);

  const userTodos = todos.filter((t) => t.source === "user");
  const agentTodos = todos.filter((t) => t.source === "agent");
  const board = boardWord(state);

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
    if (tab === "manual") {
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

  const dockItems = [
    { icon: "⌂", label: "Home", active: tab === "home", onClick: () => setTab("home") },
    { icon: "☑", label: "Tasks", active: tab === "manual", onClick: () => setTab("manual") },
    { icon: "◎", label: "Gallery", active: tab === "gallery", onClick: () => setTab("gallery") },
    {
      icon: "▦",
      label: "Workspace",
      active: tab === "workspace",
      onClick: () => setTab("workspace"),
    },
    {
      icon: "⚙",
      label: "Settings",
      active: tab === "settings",
      onClick: () => setTab("settings"),
      badge: updates?.channels?.some((c) => c.newer) ? "!" : undefined,
    },
  ];

  return (
    <div className="amy-shell">
      <div className={`amy-boot${booting ? "" : " is-done"}`} aria-hidden={!booting}>
        <div className="amy-boot__mark">
          <TechText
            text="AMY"
            intro="assemble"
            introDuration={1.5}
            reveal="letter"
            fontSize={96}
            align="center"
            color="#e7f0f7"
            accentColor="#4db8e8"
            sweep
            clickKick={false}
          />
        </div>
      </div>

      {!booting ? (
        <div className="amy-laser" aria-hidden>
          <LaserFlow
            intro
            intensity={0.28}
            color="#4db8e8"
            mouseInteraction={false}
            beamWidth={0.3}
          />
        </div>
      ) : null}

      <div className="amy-shell__body">
        {envLine ? (
          <div className="amy-env" aria-live="polite">
            <span className="amy-env__label">Context</span>
            <span className="amy-env__text">{envLine}</span>
          </div>
        ) : null}

        {tab === "home" ? (
          <>
            <div className="amy-home">
              <section className="amy-panel amy-orb-panel">
                <div className="amy-panel__head">
                  <h2>Visualizer</h2>
                  <WarmTooltip content="Crystalized Ball ↔ Strands">
                    <span>
                      <SquishSwitch
                        checked={strandsOrb}
                        onChange={setStrandsOrb}
                        label="Strands"
                        ariaLabel="Use Strands orb"
                      />
                    </span>
                  </WarmTooltip>
                </div>
                {strandsOrb ? (
                  <Strands level={audioLevel} interactive listening={state === "listening"} />
                ) : (
                  <AmyOrb state={state} audioLevel={audioLevel} compact interactive />
                )}
                <div className="amy-status-board">
                  <SplitFlapText
                    text={board}
                    padTo={8}
                    fontSize={18}
                    align="center"
                    loop={false}
                    tileStyle="minimal"
                  />
                </div>
                {(state === "thinking" || busy) && (
                  <LatticeLoader status="working" label="Agent" />
                )}
              </section>

              <section className="amy-panel">
                <div className="amy-panel__head">
                  <h2>Now</h2>
                  <StatusMark
                    status={
                      state === "error"
                        ? "failed"
                        : state === "thinking" || busy
                          ? "running"
                          : state === "idle"
                            ? "pending"
                            : "done"
                    }
                  />
                </div>
                {caption.trim() ? (
                  <p className={`amy-caption dash-caption--${captionRole || "speak"}`}>
                    <DecryptedText text={caption.trim().slice(0, 220)} animateOn="view" />
                  </p>
                ) : (
                  <p className="amy-empty">
                    <DecryptedText
                      text="Listening for hey chloe — or type below."
                      animateOn="view"
                    />
                  </p>
                )}
                {detail.trim() && detail !== caption ? (
                  <p className="dash-meta">{detail.slice(0, 120)}</p>
                ) : null}

                <div className="amy-metrics" style={{ marginTop: "1rem" }}>
                  {sys?.cpu_percent != null ? (
                    <div className="amy-metric">
                      <div className="amy-metric__row">
                        <span>CPU</span>
                        <span>{sys.cpu_percent.toFixed(0)}%</span>
                      </div>
                      {pctBar(sys.cpu_percent)}
                    </div>
                  ) : null}
                  {sys?.ram ? (
                    <div className="amy-metric">
                      <div className="amy-metric__row">
                        <span>RAM</span>
                        <span>
                          {sys.ram.used_gb}/{sys.ram.total_gb} GB
                        </span>
                      </div>
                      {pctBar(sys.ram.percent)}
                    </div>
                  ) : null}
                  <div className="amy-metric__row amy-flags" style={{ marginTop: "0.35rem" }}>
                    <span data-on={meta.voice}>voice</span>
                    <span data-on={meta.wake}>wake</span>
                    <span>{meta.lan ? "lan" : "local"}</span>
                  </div>
                </div>
              </section>
            </div>

            <FlashCards
              cards={cards}
              activity={activity}
              busy={busy || state === "thinking"}
              onAsk={(prompt) => onSendMessage(prompt)}
            />
          </>
        ) : null}

        {tab === "manual" ? (
          <section className="amy-panel amy-manual">
            <div className="amy-panel__head">
              <h2>Task board</h2>
              <RubberSegment
                items={[
                  { value: "add", label: "Add" },
                  { value: "wake", label: "Wake" },
                  { value: "hil", label: "HIL" },
                ]}
                defaultValue="add"
                onChange={(v) => {
                  if (v === "wake") onWake();
                  if (v === "hil") setHilOpen(true);
                }}
              />
            </div>
            <p className="dash-meta">
              Todo board only. Agent rows sync from live Hive tasks. Prefix `/run ` in the
              composer to send Amy a command.
            </p>

            <div className="amy-todo-add">
              <input
                value={newTodo}
                onChange={(e) => setNewTodo(e.target.value)}
                placeholder="New task for you…"
                autoComplete="off"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addTodo(newTodo);
                  }
                }}
              />
              <FuseButton label="Add" onCommit={() => addTodo(newTodo)} />
            </div>

            <div className="amy-todo-grid">
              <div>
                <h3>Yours</h3>
                <div className="amy-checklist">
                  {userTodos.map((item) => (
                    <SpringCheck
                      key={item.id}
                      checked={item.done}
                      label={item.label}
                      onChange={(done) =>
                        setTodos((rows) =>
                          rows.map((r) => (r.id === item.id ? { ...r, done } : r)),
                        )
                      }
                    />
                  ))}
                  {userTodos.length === 0 ? (
                    <p className="amy-empty">No personal tasks yet.</p>
                  ) : null}
                </div>
              </div>
              <div>
                <h3>Agent</h3>
                <div className="amy-checklist">
                  {agentTodos.map((item) => (
                    <SpringCheck
                      key={item.id}
                      checked={item.done}
                      label={item.label}
                      onChange={(done) =>
                        setTodos((rows) =>
                          rows.map((r) => (r.id === item.id ? { ...r, done } : r)),
                        )
                      }
                    />
                  ))}
                  {agentTodos.length === 0 ? (
                    <p className="amy-empty">Quiet — no agent tasks.</p>
                  ) : null}
                </div>
              </div>
            </div>
          </section>
        ) : null}

        {tab === "gallery" ? (
          <section className="amy-panel amy-gallery">
            <div className="amy-panel__head">
              <h2>AI Gallery</h2>
              <span className="dash-meta">{galleryImages.length} from tools</span>
            </div>
            {galleryImages.length === 0 ? (
              <p className="amy-empty">
                Empty until tools return real image URLs (search / fetch / vision). No placeholders.
              </p>
            ) : (
              <>
                <div className="amy-gallery__orbit">
                  <OrbitImages images={galleryImages} height="100%" width="100%" />
                </div>
                <CircularCarousel
                  items={galleryImages.map((src, i) => ({
                    src,
                    title: cards.find((c) => c.url === src)?.title || `Media ${i + 1}`,
                  }))}
                />
              </>
            )}
          </section>
        ) : null}

        {tab === "workspace" ? (
          <WorkspacePanel onAskAmy={(msg) => onSendMessage(msg)} />
        ) : null}

        {tab === "settings" ? (
          <div className="amy-settings">
            <section className="amy-panel amy-settings-nav">
              <RubberSegment
                items={[
                  { value: "controls", label: "Controls" },
                  { value: "voice", label: "Voice" },
                  { value: "integrations", label: "Integrations" },
                  { value: "config", label: "Config" },
                ]}
                value={settingsPane}
                onChange={(v) => setSettingsPane(v as SettingsPane)}
                equalSlots
              />
            </section>

            {settingsPane === "controls" ? (
              <section className="amy-panel">
                <div className="amy-panel__head">
                  <h2>Controls</h2>
                </div>
                <p className="dash-meta">Live host status only — no preview dials.</p>
                <div className="amy-settings__controls amy-settings__controls--real">
                  <FuseButton
                    label="Check updates"
                    onCommit={() => void api.updates(true).then(setUpdates)}
                  />
                  <FuseButton label="Wake mic" onCommit={() => onWake()} />
                  {updates ? (
                    <p className="dash-meta">
                      Build {updates.local_version || "—"}
                      {updates.checked_at
                        ? ` · checked ${new Date(updates.checked_at * 1000).toLocaleTimeString()}`
                        : ""}
                    </p>
                  ) : null}
                  {vision ? (
                    <p className="dash-meta">Vision: {vision.people_count} enrolled</p>
                  ) : null}
                  {sys?.cpu_percent != null ? (
                    <p className="dash-meta">CPU {sys.cpu_percent.toFixed(0)}%</p>
                  ) : null}
                </div>
              </section>
            ) : null}

            {settingsPane === "voice" ? <SettingsPanel /> : null}
            {settingsPane === "integrations" ? <IntegrationsPanel /> : null}
            {settingsPane === "config" ? (
              <Suspense fallback={<LatticeLoader />}>
                <ConfigStudio />
              </Suspense>
            ) : null}
          </div>
        ) : null}

        {error ? <p className="amy-err">{error}</p> : null}
      </div>

      <div className="amy-prompt-wrap">
        <Composer
          placeholder={
            tab === "manual"
              ? "Add a task… (or /run tell Amy something)"
              : "Tell Amy what to do — she can surf the web…"
          }
          busy={busy || state === "thinking"}
          onSend={handleSend}
          onWake={onWake}
          onStop={onBarge}
        />
      </div>

      <div className="amy-dock-wrap">
        <Dock items={dockItems} position="bottom" theme="dark" accentColor="#4db8e8" />
      </div>

      <div className="amy-toasts">
        {toasts.map((t) => (
          <SwipeToast
            key={t.id}
            title={t.title}
            description={t.body}
            onClose={() => setToasts((rows) => rows.filter((x) => x.id !== t.id))}
          />
        ))}
      </div>

      {hilOpen ? (
        <div className="amy-hil">
          <div className="amy-hil__card">
            <h2 style={{ margin: 0 }}>Confirm</h2>
            <p className="amy-empty">Hold to approve this agent action.</p>
            <HoldButton onHold={() => setHilOpen(false)}>Hold to approve</HoldButton>
            <button type="button" className="ghost" onClick={() => setHilOpen(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
