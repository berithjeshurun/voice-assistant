import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import Folder from "./reactbits/Folder";
import FuseButton from "./reactbits/FuseButton";
import SpringCheck from "./reactbits/SpringCheck";
import SquishSwitch from "./reactbits/SquishSwitch";
import "./WorkspacePanel.css";

type Pack = { id: string; name: string; path?: string; steam_root?: string };

export default function WorkspacePanel({
  onAskAmy,
}: {
  onAskAmy?: (msg: string) => void;
}) {
  const [packs, setPacks] = useState<Pack[]>([]);
  const [roots, setRoots] = useState<string[]>([]);
  const [enabled, setEnabled] = useState<string[]>([]);
  const [draftEnabled, setDraftEnabled] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const res = await api.packs();
      setPacks((res.packs || []) as Pack[]);
      setRoots(res.roots || []);
      const en = (res as { enabled?: string[] }).enabled || [];
      setEnabled(en);
      setDraftEnabled(en);
      if (!selected && res.packs?.[0]) setSelected(res.packs[0].id);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const active = useMemo(
    () => packs.find((p) => p.id === selected) || null,
    [packs, selected],
  );

  const dirty =
    draftEnabled.slice().sort().join("|") !== enabled.slice().sort().join("|");

  const saveEnabled = async () => {
    setBusy(true);
    setMsg("");
    try {
      const studio = await api.configStudio();
      await api.saveConfigStudio({
        values: {},
        apps_enabled: draftEnabled,
      });
      setEnabled(draftEnabled);
      setMsg("Pack enable list saved — restart Amy to load tools.");
      void studio;
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const folderItems = packs.map((p) => ({
    title: p.name || p.id,
    description: draftEnabled.includes(p.id) ? "enabled" : "available",
  }));

  return (
    <section className="work amy-panel">
      <div className="amy-panel__head">
        <h2>Workspace</h2>
        <span className="dash-meta">{packs.length} packs</span>
      </div>

      <div className="work__grid">
        <div className="work__folder">
          <Folder
            label="Amy"
            items={
              folderItems.length
                ? folderItems
                : [
                    { title: "Config", description: "hive.yaml" },
                    { title: "Packs", description: "none discovered" },
                  ]
            }
            onItemClick={(_item, index) => {
              const pack = packs[index];
              if (pack) setSelected(pack.id);
            }}
          />
        </div>

        <div className="work__side">
          <h3>App packs</h3>
          <p className="dash-meta">Toggle packs, then save. Click a folder page to inspect.</p>
          <div className="work__checks">
            {packs.map((p) => (
              <SpringCheck
                key={p.id}
                label={`${p.name || p.id}${enabled.includes(p.id) ? "" : ""}`}
                checked={draftEnabled.includes(p.id)}
                onChange={(on) =>
                  setDraftEnabled((prev) =>
                    on
                      ? Array.from(new Set([...prev, p.id]))
                      : prev.filter((x) => x !== p.id),
                  )
                }
              />
            ))}
            {packs.length === 0 ? <p className="amy-empty">No packs discovered.</p> : null}
          </div>

          <div className="work__actions">
            <FuseButton
              label={busy ? "Saving…" : dirty ? "Save pack list" : "Saved"}
              disabled={busy || !dirty}
              onCommit={() => void saveEnabled()}
            />
            {active ? (
              <FuseButton
                label={`Ask Amy about ${active.name}`}
                onCommit={() =>
                  onAskAmy?.(
                    `Open and summarize the workspace pack ${active.name} at ${active.path || active.id}`,
                  )
                }
              />
            ) : null}
          </div>

          {active ? (
            <div className="work__detail">
              <strong>{active.name}</strong>
              <p className="dash-meta">{active.id}</p>
              {active.path ? (
                <p className="dash-meta work__path">{active.path}</p>
              ) : null}
              <SquishSwitch
                checked={draftEnabled.includes(active.id)}
                label="Enabled"
                onChange={(on) =>
                  setDraftEnabled((prev) =>
                    on
                      ? Array.from(new Set([...prev, active.id]))
                      : prev.filter((x) => x !== active.id),
                  )
                }
              />
            </div>
          ) : null}

          {roots.length ? (
            <div className="work__roots">
              <p className="dash-meta">Roots</p>
              {roots.map((r) => (
                <code key={r}>{r}</code>
              ))}
            </div>
          ) : null}
          {msg ? <p className="dash-meta">{msg}</p> : null}
        </div>
      </div>
    </section>
  );
}
