import { useEffect, useState } from "react";
import {
  ActivityChip,
  AssistantState,
  getToken,
  HiveTask,
  HudCard,
  openAmySocket,
  Snapshot,
  api,
} from "../api";
import ActivityDock from "./ActivityDock";

export default function DockView() {
  const [token] = useState(getToken());
  const [state, setState] = useState<AssistantState>("idle");
  const [tools, setTools] = useState<string[]>([]);
  const [activity, setActivity] = useState<ActivityChip[]>([]);
  const [cards, setCards] = useState<HudCard[]>([]);
  const [tasks, setTasks] = useState<HiveTask[]>([]);
  const [detail, setDetail] = useState("");

  useEffect(() => {
    if (!token) return;
    let ws: WebSocket | null = null;
    let cancelled = false;
    (async () => {
      try {
        const s = await api.snapshot();
        if (cancelled) return;
        setState(s.state);
        setTools(s.tools || []);
        setActivity(s.activity || []);
        setCards(s.cards || []);
        setTasks(s.tasks || []);
        setDetail(s.detail || "");
      } catch {
        /* host may still be booting */
      }
    })();
    ws = openAmySocket((snap: Snapshot) => {
      setState(snap.state);
      if (Array.isArray(snap.tools)) setTools(snap.tools);
      if (Array.isArray(snap.activity)) setActivity(snap.activity);
      if (Array.isArray(snap.cards)) setCards(snap.cards);
      if (Array.isArray(snap.tasks)) setTasks(snap.tasks);
      if (typeof snap.detail === "string") setDetail(snap.detail);
    });
    return () => {
      cancelled = true;
      ws?.close();
    };
  }, [token]);

  if (!token) {
    return <div className="amy-dock amy-dock--gate">Amy dock — waiting for token</div>;
  }

  return (
    <div className="amy-dock-shell">
      <ActivityDock
        state={state}
        tools={tools}
        activity={activity}
        cards={cards}
        tasks={tasks}
        detail={detail}
      />
    </div>
  );
}
