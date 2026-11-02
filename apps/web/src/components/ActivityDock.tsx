import type { ActivityChip, AssistantState, HiveTask, HudCard } from "../api";
import { api } from "../api";

const CAPABILITY_LABELS: Record<string, string> = {
  web_search: "Search",
  web_fetch: "Fetch",
  os_volume: "Volume",
  os_mute: "Mute",
  os_brightness: "Brightness",
  os_toggle: "Dark mode",
  os_open_app: "Apps",
  browse_url: "Browse",
  play_youtube: "YouTube",
  os_power: "Power",
  bambu_status: "Bambu",
  bambu_control: "Print",
  slicer_find: "Slicer",
  slicer_open: "Open 3MF",
  read_file: "Files",
  hive_delegate: "Hive",
};

type Props = {
  state: AssistantState;
  tools: string[];
  activity: ActivityChip[];
  cards: HudCard[];
  tasks?: HiveTask[];
  detail?: string;
  compact?: boolean;
};

function weatherFromCards(cards: HudCard[]): ActivityChip | null {
  for (const c of cards) {
    const blob = `${c.title} ${c.snippet}`.toLowerCase();
    if (blob.includes("weather") || blob.includes("forecast") || blob.includes("°")) {
      return {
        kind: "weather",
        label: (c.title || "Weather").slice(0, 42),
        detail: (c.snippet || "").slice(0, 64),
      };
    }
  }
  return null;
}

export default function ActivityDock({
  state,
  tools,
  activity,
  cards,
  tasks = [],
  detail = "",
  compact = false,
}: Props) {
  const weather = weatherFromCards(cards) || activity.find((a) => a.kind === "weather");
  const recent = activity.filter((a) => a.kind !== "weather").slice(0, 5);
  const liveTasks = tasks.filter((t) => t.status === "running").slice(0, 4);
  const doneTasks = tasks
    .filter((t) => t.status !== "running")
    .slice(0, compact ? 2 : 4);
  const caps = tools
    .filter((t) => CAPABILITY_LABELS[t])
    .slice(0, compact ? 6 : 10)
    .map((t) => ({ id: t, label: CAPABILITY_LABELS[t] }));

  const onCancel = async (taskId: string) => {
    try {
      await api.cancelHiveTask(taskId);
    } catch {
      /* ignore — host may be down */
    }
  };

  return (
    <div className={`amy-dock ${compact ? "amy-dock--compact" : ""}`.trim()} data-state={state}>
      <div className="amy-dock__live">
        <span className="amy-dock__pill amy-dock__pill--state">
          <span className="dot" />
          {state.replace("_", " ")}
        </span>
        {detail ? <span className="amy-dock__detail">{detail}</span> : null}
        {weather ? (
          <span className="amy-dock__pill amy-dock__pill--weather" title={weather.detail}>
            {weather.label}
          </span>
        ) : null}
        {liveTasks.map((t) => (
          <span
            key={t.task_id}
            className="amy-dock__pill amy-dock__pill--hive amy-dock__pill--hive-running"
            title={t.goal || t.task_id}
          >
            <span>
              {(t.agent_name || t.agent_id || "hive").slice(0, 16)}…{" "}
              {t.max_steps ? `≤${t.max_steps} steps` : "running"}
            </span>
            <button
              type="button"
              className="amy-dock__cancel"
              aria-label={`Cancel ${t.agent_name || t.agent_id}`}
              onClick={() => onCancel(t.task_id)}
            >
              ×
            </button>
          </span>
        ))}
        {doneTasks.map((t) => (
          <span
            key={t.task_id}
            className={`amy-dock__pill amy-dock__pill--hive amy-dock__pill--hive-${t.status}`}
            title={(t.output || t.goal || "").slice(0, 120)}
          >
            {(t.agent_name || t.agent_id || "hive").slice(0, 14)}:{t.status}
            {typeof t.ms === "number" && t.ms > 0 ? ` ${t.ms}ms` : ""}
          </span>
        ))}
        {recent.map((a, i) => (
          <span
            key={`${a.kind}-${a.label}-${i}`}
            className={`amy-dock__pill amy-dock__pill--${a.kind}`}
            title={a.detail || a.label}
          >
            {a.kind === "tool" ? `⚙ ${a.label}` : a.label}
          </span>
        ))}
      </div>
      <div className="amy-dock__caps" aria-label="Capabilities">
        {caps.map((c) => (
          <span key={c.id} className="amy-dock__cap">
            {c.label}
          </span>
        ))}
      </div>
    </div>
  );
}
