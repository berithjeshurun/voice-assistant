import { useMemo, useState } from "react";
import { ActivityChip, HudCard } from "../api";
import CallChip from "./reactbits/CallChip";
import FuseButton from "./reactbits/FuseButton";
import StatusMark from "./reactbits/StatusMark";
import "./FlashCards.css";

type Props = {
  cards: HudCard[];
  activity: ActivityChip[];
  busy?: boolean;
  onOpen?: (card: HudCard) => void;
  onAsk?: (prompt: string) => void;
};

function kindLabel(kind: string): string {
  const k = (kind || "result").toLowerCase();
  if (k.includes("news")) return "News";
  if (k.includes("web") || k.includes("search")) return "Web";
  if (k.includes("weather")) return "Weather";
  if (k.includes("tool")) return "Tool";
  return kind || "Result";
}

export default function FlashCards({ cards, activity, busy, onOpen, onAsk }: Props) {
  const [dismissed, setDismissed] = useState<Set<string>>(() => new Set());
  const [focus, setFocus] = useState(0);

  const toolActivity = useMemo(
    () => activity.filter((a) => a.kind === "tool" || a.kind === "hive" || a.kind === "status"),
    [activity],
  );

  const visible = useMemo(() => {
    return cards
      .map((c, i) => ({ ...c, _key: `${c.url || c.title}-${i}` }))
      .filter((c) => !dismissed.has(c._key));
  }, [cards, dismissed]);

  if (!visible.length && !toolActivity.length) {
    return (
      <section className="flash amy-panel">
        <div className="amy-panel__head">
          <h2>Live results</h2>
          <StatusMark status={busy ? "running" : "pending"} />
        </div>
        <p className="amy-empty">
          No tool cards yet — ask Amy to search the web or fetch news and results appear here.
        </p>
      </section>
    );
  }

  const active = visible[Math.min(focus, Math.max(0, visible.length - 1))] || null;

  return (
    <section className="flash amy-panel">
      <div className="amy-panel__head">
        <h2>Live results</h2>
        <span className="dash-meta">{visible.length} cards</span>
      </div>

      {toolActivity.length ? (
        <div className="flash__chips">
          {toolActivity.slice(0, 6).map((a, i) => (
            <CallChip
              key={`${a.label}-${i}`}
              name={a.label || "tool"}
              argument={(a.detail || "").slice(0, 36)}
              status={busy ? "running" : "done"}
              icon={
                (a.label || "").toLowerCase().includes("search") ||
                (a.detail || "").toLowerCase().includes("http")
                  ? "search"
                  : "terminal"
              }
            />
          ))}
        </div>
      ) : null}

      {visible.length ? (
        <div className="flash__rail" role="list">
          {visible.map((c, i) => (
            <button
              key={c._key}
              type="button"
              role="listitem"
              className={`flash__tile${i === focus ? " is-active" : ""}`}
              onClick={() => setFocus(i)}
            >
              <span className="flash__kind">{kindLabel(c.kind)}</span>
              <strong>{c.title || "Untitled"}</strong>
              {c.snippet ? <p>{c.snippet.slice(0, 110)}</p> : null}
            </button>
          ))}
        </div>
      ) : null}

      {active ? (
        <div className="flash__focus">
          <div className="flash__focus-top">
            <span className="flash__kind">{kindLabel(active.kind)}</span>
            <StatusMark status="done" />
          </div>
          <h3>{active.title || "Result"}</h3>
          {active.snippet ? <p>{active.snippet}</p> : null}
          {active.url ? (
            <p className="flash__url" title={active.url}>
              {active.url}
            </p>
          ) : null}
          <div className="flash__actions">
            {active.url ? (
              <FuseButton
                label="Open"
                onCommit={() => {
                  onOpen?.(active);
                  window.open(active.url, "_blank", "noopener,noreferrer");
                }}
              />
            ) : null}
            <FuseButton
              label="Ask Amy"
              onCommit={() =>
                onAsk?.(
                  `Follow up on this ${kindLabel(active.kind).toLowerCase()} result: ${active.title}${
                    active.url ? ` (${active.url})` : ""
                  }. ${active.snippet || ""}`.slice(0, 400),
                )
              }
            />
            <button
              type="button"
              className="ghost"
              onClick={() => {
                setDismissed((prev) => new Set(prev).add(active._key));
                setFocus(0);
              }}
            >
              Dismiss
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
