import type { HudCard } from "../api";

type Props = {
  caption: string;
  role: string;
  cards: HudCard[];
  compact?: boolean;
};

export default function CaptionBar({ caption, role, cards, compact = false }: Props) {
  if (!caption && cards.length === 0) return null;
  return (
    <div className={`caption-block ${compact ? "caption-block--compact" : ""}`.trim()}>
      {caption ? (
        <p className="caption" data-role={role || "speak"} aria-live="polite">
          {role === "user" ? (
            <span className="caption__who">You</span>
          ) : role === "ack" ? (
            <span className="caption__who">Amy</span>
          ) : role === "status" ? (
            <span className="caption__who">Status</span>
          ) : (
            <span className="caption__who">Amy</span>
          )}
          {caption}
        </p>
      ) : null}
      {cards.length > 0 ? (
        <div className="hud-cards" aria-label="Web results">
          {cards.map((c, i) => {
            const inner = (
              <>
                <span className="hud-card__title">{c.title || c.url || "Result"}</span>
                {c.snippet ? <span className="hud-card__snip">{c.snippet}</span> : null}
              </>
            );
            return c.url ? (
              <a
                key={`${c.url}-${i}`}
                className="hud-card"
                href={c.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                {inner}
              </a>
            ) : (
              <div key={`card-${i}`} className="hud-card hud-card--static">
                {inner}
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
