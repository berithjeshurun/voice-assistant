import { FormEvent, useEffect, useState } from "react";
import { api, ApiError, ReminderItem } from "../api";

type Props = {
  reminders: ReminderItem[];
  /** viewer devices can see reminders but not add or cancel them */
  canEdit?: boolean;
  onError?: (msg: string) => void;
};

const QUICK_TIMERS = ["5 minutes", "10 minutes", "25 minutes"];

/** "in 45 s", "in 12 min", "6:30 PM", "tomorrow 9:00 AM", "Fri 5:00 PM". */
export function formatDue(dueTs: number, nowMs: number): string {
  const due = new Date(dueTs * 1000);
  const secs = Math.round(dueTs - nowMs / 1000);
  if (secs <= 0) return "now";
  if (secs < 60) return `in ${secs} s`;
  if (secs < 3600) return `in ${Math.round(secs / 60)} min`;
  const time = due.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const now = new Date(nowMs);
  const dayDiff = Math.round(
    (new Date(due.getFullYear(), due.getMonth(), due.getDate()).getTime() -
      new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()) /
      86_400_000,
  );
  if (dayDiff === 0) return time;
  if (dayDiff === 1) return `tomorrow ${time}`;
  if (dayDiff < 7) return `${due.toLocaleDateString([], { weekday: "short" })} ${time}`;
  return `${due.toLocaleDateString([], { day: "numeric", month: "short" })} ${time}`;
}

function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message.replace(/^\d+\s+/, "");
  return e instanceof Error ? e.message : String(e);
}

export default function RemindersPanel({ reminders, canEdit = true, onError }: Props) {
  const [now, setNow] = useState(Date.now());
  const [what, setWhat] = useState("");
  const [when, setWhen] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setNow(Date.now());
    const t = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => window.clearInterval(t);
  }, [reminders]);

  const run = async (fn: () => Promise<{ message?: string }>) => {
    setBusy(true);
    setNote("");
    try {
      const out = await fn();
      setNote(out.message || "");
      return true;
    } catch (e) {
      const msg = errorText(e);
      setNote(msg);
      onError?.(msg);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (!what.trim() || !when.trim()) return;
    const ok = await run(async () => (await api.addReminder({ text: what, when })).reminder);
    if (ok) {
      setWhat("");
      setWhen("");
    }
  };

  const sorted = [...reminders].sort((a, b) => a.due_ts - b.due_ts);

  return (
    <section className="amy-panel amy-reminders" aria-label="Reminders">
      <div className="amy-panel__head">
        <h2>Reminders</h2>
        <span className="dash-meta">{sorted.length} upcoming</span>
      </div>

      {canEdit ? (
        <>
          <form className="amy-reminders__add" onSubmit={add}>
            <input
              value={what}
              onChange={(e) => setWhat(e.target.value)}
              placeholder="Remind me to…"
              aria-label="What to remember"
              maxLength={300}
            />
            <input
              value={when}
              onChange={(e) => setWhen(e.target.value)}
              placeholder="when — e.g. at 6pm, tomorrow at 9, in 20 min"
              aria-label="When"
              maxLength={120}
            />
            <button type="submit" disabled={busy || !what.trim() || !when.trim()}>
              Add
            </button>
          </form>
          <div className="amy-reminders__quick">
            {QUICK_TIMERS.map((d) => (
              <button
                key={d}
                type="button"
                disabled={busy}
                onClick={() => void run(async () => (await api.addReminder({ timer: d })).reminder)}
              >
                ⏱ {d.replace(" minutes", " min")}
              </button>
            ))}
          </div>
        </>
      ) : null}
      {note ? (
        <p className="dash-meta" role="status">
          {note}
        </p>
      ) : null}

      <ul className="amy-reminders__list">
        {sorted.map((r) => (
          <li key={r.id} data-kind={r.kind}>
            <span className="amy-reminders__icon" aria-hidden>
              {r.kind === "timer" ? "⏱" : "⏰"}
            </span>
            <span className="amy-reminders__text">
              {r.kind === "timer" && r.text === "timer" ? "Timer" : r.text}
              {r.repeat_text ? <small> · {r.repeat_text}</small> : null}
            </span>
            <time dateTime={new Date(r.due_ts * 1000).toISOString()}>{formatDue(r.due_ts, now)}</time>
            {canEdit ? (
              <button
                type="button"
                aria-label={`Cancel ${r.text}`}
                disabled={busy}
                onClick={() => void run(() => api.cancelReminder(r.id))}
              >
                ✕
              </button>
            ) : null}
          </li>
        ))}
        {sorted.length === 0 ? (
          <li className="amy-empty">No reminders. Try “remind me to stretch in 30 minutes”.</li>
        ) : null}
      </ul>
    </section>
  );
}
