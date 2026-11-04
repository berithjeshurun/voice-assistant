import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityChip,
  api,
  ApprovalRequest,
  AssistantState,
  ChatMessage,
  getToken,
  GuardStatus,
  HiveTask,
  HudCard,
  openAmySocket,
  Snapshot,
} from "../api";
import ActivityDock from "./ActivityDock";
import GuardPanel from "./GuardPanel";

type ThreadItem = {
  id: string;
  role: "user" | "assistant" | "ack" | "status";
  text: string;
  ts: number;
  cards?: HudCard[];
};

function roleLabel(role: ThreadItem["role"]): string {
  if (role === "user") return "YOU";
  if (role === "ack") return "ACK";
  if (role === "status") return "SYS";
  return "AMY";
}

function mapHistory(history: ChatMessage[]): ThreadItem[] {
  return history.map((m, i) => ({
    id: `h-${m.ts}-${i}`,
    role: m.role === "user" ? "user" : "assistant",
    text: m.text,
    ts: m.ts || Date.now() / 1000,
  }));
}

function copyText(text: string) {
  void navigator.clipboard?.writeText(text).catch(() => undefined);
}

function clockLabel(ts: number): string {
  try {
    return new Date(ts * 1000).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

export default function ChatView() {
  const [token] = useState(getToken());
  const [state, setState] = useState<AssistantState>("idle");
  const [items, setItems] = useState<ThreadItem[]>([]);
  const [liveCards, setLiveCards] = useState<HudCard[]>([]);
  const [tools, setTools] = useState<string[]>([]);
  const [activity, setActivity] = useState<ActivityChip[]>([]);
  const [tasks, setTasks] = useState<HiveTask[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [guard, setGuard] = useState<GuardStatus | undefined>(undefined);
  const [detail, setDetail] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const lastCaptionKey = useRef("");

  const applySnap = (s: Snapshot) => {
    setState(s.state);
    if (Array.isArray(s.cards)) setLiveCards(s.cards);
    if (Array.isArray(s.tools)) setTools(s.tools);
    if (Array.isArray(s.activity)) setActivity(s.activity);
    if (Array.isArray(s.tasks)) setTasks(s.tasks);
    if (Array.isArray(s.approvals)) setApprovals(s.approvals);
    if (s.guard) setGuard(s.guard);
    if (typeof s.detail === "string") setDetail(s.detail);

    const caption = (s.caption || "").trim();
    const role = (s.caption_role || "speak").trim();
    if (!caption) return;

    const key = `${role}:${caption}`;
    if (key === lastCaptionKey.current) {
      if ((role === "speak" || role === "ack") && (s.cards?.length || 0) > 0) {
        setItems((prev) => {
          if (!prev.length) return prev;
          const next = [...prev];
          const last = { ...next[next.length - 1] };
          if (last.role === "assistant" || last.role === "ack") {
            last.cards = s.cards;
            next[next.length - 1] = last;
          }
          return next;
        });
      }
      return;
    }
    lastCaptionKey.current = key;

    const mapped: ThreadItem["role"] =
      role === "user" ? "user" : role === "ack" ? "ack" : role === "status" ? "status" : "assistant";

    setItems((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.role === mapped && last.text === caption) {
        return prev;
      }
      return [
        ...prev,
        {
          id: `c-${Date.now()}-${prev.length}`,
          role: mapped,
          text: caption,
          ts: Date.now() / 1000,
          cards: mapped === "assistant" || mapped === "ack" ? s.cards || [] : undefined,
        },
      ];
    });
  };

  useEffect(() => {
    if (!token) return;
    let ws: WebSocket | null = null;
    let cancelled = false;
    (async () => {
      try {
        const [h, snap] = await Promise.all([api.health(), api.snapshot()]);
        if (cancelled) return;
        setState(h.state);
        setItems(mapHistory(h.history || []));
        setTools(snap.tools || []);
        setActivity(snap.activity || []);
        setLiveCards(snap.cards || []);
        setDetail(snap.detail || "");
        setApprovals(snap.approvals || []);
        setGuard(snap.guard);
        setError("");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    ws = openAmySocket(applySnap);
    return () => {
      cancelled = true;
      ws?.close();
    };
  }, [token]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [items, busy, liveCards]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const msg = text.trim();
    if (!msg || busy) return;
    setBusy(true);
    setError("");
    setText("");
    setItems((prev) => [
      ...prev,
      { id: `u-${Date.now()}`, role: "user", text: msg, ts: Date.now() / 1000 },
    ]);
    try {
      const res = await api.turn(msg);
      if (!res.ok) throw new Error(res.error || "turn failed");
      const reply = res.reply || "(no reply)";
      setItems((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          text: reply,
          ts: Date.now() / 1000,
          cards: liveCards.length ? liveCards : undefined,
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const headerState = useMemo(() => state.replace("_", " "), [state]);
  const homeChip = activity.find((a) => a.kind === "weather");

  if (!token) {
    return (
      <div className="hud hud--gate">
        <div className="hud__frame">
          <h1>Amy</h1>
          <p>Open this panel from the host (token required).</p>
        </div>
      </div>
    );
  }

  return (
    <div className="hud" data-state={state}>
      <div className="hud__corners" aria-hidden />
      <header className="hud__top">
        <div className="hud__brand">
          <span className="hud__mark">AMY</span>
          <span className="hud__channel">VOICE HUD</span>
        </div>
        <div className="hud__meta">
          {homeChip ? <span className="hud__chip">{homeChip.label}</span> : null}
          <span className="hud__state" data-state={state}>
            <span className="dot" />
            {headerState}
          </span>
        </div>
      </header>

      <div className="hud__thread" aria-live="polite">
        {items.length === 0 && (
          <div className="hud__empty">
            <p>Listening for wake · captions stream here</p>
            <span>Orb left · this panel right</span>
          </div>
        )}
        {items.map((m) => (
          <article key={m.id} className={`hud-row hud-row--${m.role}`}>
            <div className="hud-line">
              <header className="hud-line__head">
                <span>{roleLabel(m.role)}</span>
                <time>{clockLabel(m.ts)}</time>
              </header>
              <div className="hud-line__body">{m.text}</div>
              {m.cards && m.cards.length > 0 ? (
                <div className="hud-results" aria-label="Results">
                  {m.cards.map((c, i) => (
                    <div key={`${c.url || c.title}-${i}`} className="hud-result">
                      <strong>{c.title || c.url || "Result"}</strong>
                      {c.snippet ? <p>{c.snippet}</p> : null}
                      <div className="hud-result__actions">
                        {c.url ? (
                          <a href={c.url} target="_blank" rel="noopener noreferrer">
                            Open
                          </a>
                        ) : null}
                        <button
                          type="button"
                          onClick={() =>
                            copyText([c.title, c.url, c.snippet].filter(Boolean).join("\n"))
                          }
                        >
                          Copy
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </article>
        ))}
        {busy && (
          <article className="hud-row hud-row--ack">
            <div className="hud-line">
              <header className="hud-line__head">
                <span>ACK</span>
              </header>
              <div className="hud-line__body">Working…</div>
            </div>
          </article>
        )}
        <div ref={bottomRef} />
      </div>

      {error ? <p className="hud__err">{error}</p> : null}

      <GuardPanel approvals={approvals} guard={guard} onError={setError} />

      <form className="hud__composer" onSubmit={onSubmit}>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Type a command…"
          autoComplete="off"
        />
        <div className="hud__actions">
          <button type="submit" disabled={busy || !text.trim()}>
            Send
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() => void api.wake().catch((e) => setError(String(e)))}
          >
            Wake
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() => void api.barge().catch((e) => setError(String(e)))}
          >
            Stop
          </button>
        </div>
      </form>

      <ActivityDock
        state={state}
        tools={tools}
        activity={activity}
        cards={liveCards}
        tasks={tasks}
        detail={detail}
        compact
      />
    </div>
  );
}
