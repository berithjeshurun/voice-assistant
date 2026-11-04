import { FormEvent, useEffect, useState } from "react";
import AmyOrb from "./components/AmyOrb";
import ChatView from "./components/ChatView";
import Dashboard from "./components/Dashboard";
import DockView from "./components/DockView";
import {
  ActivityChip,
  api,
  AssistantState,
  ChatMessage,
  getToken,
  HiveTask,
  HudCard,
  openAmySocket,
  Snapshot,
} from "./api";

function viewParam(): string {
  try {
    return (new URLSearchParams(window.location.search).get("view") || "").toLowerCase();
  } catch {
    return "";
  }
}

/** Live status under the orb — never leave the user staring at a blank “thinking”. */
function humanOrbStatus(
  state: AssistantState,
  detail: string,
  activity: { kind?: string; label?: string; detail?: string }[],
): string {
  const d = (detail || "").trim();
  const low = d.toLowerCase();
  if (low.startsWith("stt:")) return `loading speech (${d.slice(4)})…`;
  if (low === "ack" || low.includes("bridging") || low.includes("ack")) {
    return "bridging reply…";
  }
  if (low === "agent" || low === "working" || low === "text") return "working on it…";
  if (low === "tts" || low === "tts_pulse" || low === "tts_tail" || low === "early") {
    return "speaking…";
  }
  if (low === "convo" || low === "transcript" || low === "barge") return "listening…";
  if (low === "ready" || low === "idle" || low === "convo_end" || low === "spoken") {
    if (state === "idle") return "ready — say hey chloe";
  }
  const chip = activity.find(
    (a) => a.kind === "tool" || a.kind === "hive" || a.kind === "status",
  );
  if (chip?.label) {
    const extra = (chip.detail || "").trim();
    return extra ? `${chip.label}: ${extra.slice(0, 48)}` : chip.label;
  }
  if (d && !["thinking", "idle", "listening", "speaking"].includes(low)) {
    return d.slice(0, 72);
  }
  if (state === "thinking") return "working…";
  if (state === "listening") return "listening…";
  if (state === "speaking") return "speaking…";
  if (state === "idle") return "ready — say hey chloe";
  return "";
}

function isOrbOnlyView(): boolean {
  return viewParam() === "orb";
}

function isChatView(): boolean {
  return viewParam() === "chat" || viewParam() === "captions";
}

function isDockView(): boolean {
  return viewParam() === "dock" || viewParam() === "bar";
}

export default function App() {
  const [token, setToken] = useState(getToken());
  const [tokenInput, setTokenInput] = useState("");
  const [state, setState] = useState<AssistantState>("idle");
  const [audioLevel, setAudioLevel] = useState(0);
  const [caption, setCaption] = useState("");
  const [captionRole, setCaptionRole] = useState("");
  const [detail, setDetail] = useState("");
  const [activity, setActivity] = useState<ActivityChip[]>([]);
  const [cards, setCards] = useState<HudCard[]>([]);
  const [tasks, setTasks] = useState<HiveTask[]>([]);
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [meta, setMeta] = useState({ voice: false, wake: false, lan: false });
  const [orbOnly] = useState(isOrbOnlyView);
  const [chatOnly] = useState(isChatView);
  const [dockOnly] = useState(isDockView);

  const applySnap = (s: Snapshot) => {
    setState(s.state);
    setAudioLevel(typeof s.audio_level === "number" ? s.audio_level : 0);
    if (typeof s.caption === "string") setCaption(s.caption);
    if (typeof s.caption_role === "string") setCaptionRole(s.caption_role);
    if (typeof s.detail === "string") setDetail(s.detail);
    if (Array.isArray(s.activity)) setActivity(s.activity);
    if (Array.isArray(s.cards)) setCards(s.cards);
    if (Array.isArray(s.tasks)) setTasks(s.tasks);
  };

  useEffect(() => {
    if (!token) return;
    let ws: WebSocket | null = null;
    let cancelled = false;
    let poll: ReturnType<typeof setInterval> | undefined;
    (async () => {
      try {
        const h = await api.health();
        if (cancelled) return;
        setState(h.state);
        setHistory(h.history || []);
        setMeta({ voice: h.voice, wake: h.wake, lan: h.lan });
        setError("");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
      try {
        const snap = await api.snapshot();
        if (!cancelled) applySnap(snap);
      } catch {
        /* ignore — WS / next poll will fill */
      }
    })();
    ws = openAmySocket((snap) => {
      applySnap(snap);
    });
    // Orb status must stay live even if the socket stalls on “thinking”.
    if (orbOnly) {
      poll = setInterval(() => {
        api.snapshot().then(applySnap).catch(() => undefined);
      }, 900);
    }
    return () => {
      cancelled = true;
      ws?.close();
      if (poll) clearInterval(poll);
    };
  }, [token, orbOnly]);

  useEffect(() => {
    if (!orbOnly) return;
    document.documentElement.classList.add("orb-page");
    document.body.classList.add("orb-page");
    return () => {
      document.documentElement.classList.remove("orb-page");
      document.body.classList.remove("orb-page");
    };
  }, [orbOnly]);

  const saveToken = () => {
    const t = tokenInput.trim();
    if (!t) return;
    sessionStorage.setItem("amy_token", t);
    const url = new URL(window.location.href);
    url.searchParams.set("token", t);
    window.history.replaceState({}, "", url.toString());
    setToken(t);
  };

  const sendMessage = async (raw: string) => {
    const msg = raw.trim();
    if (!msg || busy) return;
    setBusy(true);
    setError("");
    setText("");
    setCaption(msg);
    setCaptionRole("user");
    setHistory((h) => [...h, { role: "user", text: msg, ts: Date.now() / 1000 }]);
    try {
      const res = await api.turn(msg);
      if (!res.ok) throw new Error(res.error || "turn failed");
      const reply = res.reply || "(no reply)";
      setCaption(reply);
      setCaptionRole("speak");
      setHistory((h) => [
        ...h,
        { role: "assistant", text: reply, ts: Date.now() / 1000 },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    await sendMessage(text);
  };

  const openFullHud = () => {
    // Native pywebview HUD — never open a browser tab from the orb.
    void api.openHud().catch((e) => {
      console.error("open_hud failed", e);
      setError(e instanceof Error ? e.message : String(e));
    });
  };

  if (!token) {
    return (
      <div className="token-gate">
        <h1>Amy</h1>
        <p>Enter the access token from the host machine link.</p>
        <input
          value={tokenInput}
          onChange={(e) => setTokenInput(e.target.value)}
          placeholder="token"
          autoFocus
        />
        <button type="button" onClick={saveToken}>
          Connect
        </button>
      </div>
    );
  }

  if (chatOnly) {
    return <ChatView />;
  }

  if (dockOnly) {
    return <DockView />;
  }

  if (orbOnly) {
    const showCaption =
      Boolean(caption.trim()) &&
      caption.trim().toLowerCase() !== "ready." &&
      (state === "speaking" ||
        state === "listening" ||
        state === "thinking" ||
        captionRole === "ack" ||
        captionRole === "speak");
    const statusLine = humanOrbStatus(state, detail, activity);
    const envChip = activity.find((a) => a.kind === "env");
    const envLine = (envChip?.detail || envChip?.label || "").trim();
    return (
      <div
        className="orb-stage"
        data-state={state}
        onDoubleClick={openFullHud}
      >
        <AmyOrb state={state} audioLevel={audioLevel} interactive />
        {showCaption ? (
          <div
            className={`orb-caption orb-caption--${captionRole || "speak"}`}
            aria-live="polite"
          >
            {caption.trim().slice(0, 220)}
          </div>
        ) : null}
        <div className="orb-stage__status" aria-live="polite">
          <span className="orb-stage__label">{state.replace("_", " ")}</span>
          {statusLine ? (
            <span className="orb-stage__detail">{statusLine}</span>
          ) : null}
          {envLine && state === "idle" ? (
            <span className="orb-stage__env">{envLine}</span>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <Dashboard
      state={state}
      audioLevel={audioLevel}
      caption={caption}
      captionRole={captionRole}
      detail={detail}
      activity={activity}
      cards={cards}
      tasks={tasks}
      history={history}
      meta={meta}
      busy={busy}
      error={error}
      text={text}
      setText={setText}
      onSubmit={onSubmit}
      onSendMessage={(msg) => void sendMessage(msg)}
      onWake={() => void api.wake().catch((e) => setError(String(e)))}
      onBarge={() => void api.barge().catch((e) => setError(String(e)))}
    />
  );
}
