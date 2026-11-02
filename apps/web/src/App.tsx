import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import AmyOrb from "./components/AmyOrb";
import CaptionBar from "./components/CaptionBar";
import ChatView from "./components/ChatView";
import DockView from "./components/DockView";
import {
  api,
  AssistantState,
  ChatMessage,
  getToken,
  HudCard,
  openAmySocket,
  Snapshot,
} from "./api";

const STATES: AssistantState[] = [
  "idle",
  "listening",
  "thinking",
  "speaking",
  "needs_approval",
];

function viewParam(): string {
  try {
    return (new URLSearchParams(window.location.search).get("view") || "").toLowerCase();
  } catch {
    return "";
  }
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
  const [cards, setCards] = useState<HudCard[]>([]);
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [meta, setMeta] = useState({ voice: false, wake: false, lan: false });
  const [orbOnly] = useState(isOrbOnlyView);
  const [chatOnly] = useState(isChatView);
  const [dockOnly] = useState(isDockView);
  const bottomRef = useRef<HTMLDivElement>(null);

  const applySnap = (s: Snapshot) => {
    setState(s.state);
    setAudioLevel(typeof s.audio_level === "number" ? s.audio_level : 0);
    if (typeof s.caption === "string") setCaption(s.caption);
    if (typeof s.caption_role === "string") setCaptionRole(s.caption_role);
    if (Array.isArray(s.cards)) setCards(s.cards);
  };

  useEffect(() => {
    if (!token) return;
    let ws: WebSocket | null = null;
    let cancelled = false;
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
    })();
    ws = openAmySocket((snap) => {
      applySnap(snap);
    });
    return () => {
      cancelled = true;
      ws?.close();
    };
  }, [token]);

  useEffect(() => {
    if (orbOnly) return;
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history, busy, orbOnly]);

  const saveToken = () => {
    const t = tokenInput.trim();
    if (!t) return;
    sessionStorage.setItem("amy_token", t);
    const url = new URL(window.location.href);
    url.searchParams.set("token", t);
    window.history.replaceState({}, "", url.toString());
    setToken(t);
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const msg = text.trim();
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

  const openFullHud = () => {
    const url = new URL(window.location.href);
    url.searchParams.delete("view");
    window.open(url.toString(), "_blank", "noopener,noreferrer");
  };

  const title = useMemo(() => "Amy", []);

  if (!token) {
    return (
      <div className="token-gate">
        <h1>{title}</h1>
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
    return (
      <div className="orb-stage" onDoubleClick={openFullHud} title="Double-click to open HUD">
        <AmyOrb state={state} audioLevel={audioLevel} interactive />
        {/* Captions live in the separate chat window (?view=chat) */}
        <span className="orb-stage__label">{state.replace("_", " ")}</span>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="brand">
        <div>
          <h1>{title}</h1>
          <p>Always-on assistant — voice on the host, HUD everywhere.</p>
        </div>
        <div className="status" data-state={state}>
          <span className="dot" />
          {state.replace("_", " ")}
        </div>
      </header>

      <div className="orb-hero" aria-hidden={false}>
        <AmyOrb state={state} audioLevel={audioLevel} compact interactive />
      </div>

      <CaptionBar caption={caption} role={captionRole} cards={cards} />

      <div className="meta">
        <span>voice {meta.voice ? "on" : "off"}</span>
        <span>wake {meta.wake ? "on" : "off"}</span>
        <span>{meta.lan ? "LAN" : "local"}</span>
      </div>

      <div className="chat" aria-live="polite">
        {history.length === 0 && (
          <div className="bubble assistant">
            <span className="who">Amy</span>
            Say hey amy on the host mic, or type here from your phone.
          </div>
        )}
        {history.map((m, i) => (
          <div key={`${m.ts}-${i}`} className={`bubble ${m.role === "user" ? "user" : "assistant"}`}>
            <span className="who">{m.role === "user" ? "You" : "Amy"}</span>
            {m.text}
          </div>
        ))}
        {busy && (
          <div className="bubble assistant">
            <span className="who">Amy</span>
            Thinking…
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {error && <p className="err">{error}</p>}

      <form className="composer" onSubmit={onSubmit}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Message Amy…"
          rows={2}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void onSubmit(e as unknown as FormEvent);
            }
          }}
        />
        <div className="actions">
          <button type="submit" disabled={busy || !text.trim()}>
            Send
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => void api.wake().catch((e) => setError(String(e)))}
          >
            Wake
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => void api.barge().catch((e) => setError(String(e)))}
          >
            Stop
          </button>
        </div>
      </form>

      <div className="demo-row" aria-label="Orb preview states">
        {STATES.map((s) => (
          <button key={s} type="button" onClick={() => void api.setState(s)}>
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
