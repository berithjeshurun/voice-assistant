import { useEffect, useState } from "react";
import { api, SettingsOptions } from "../api";

type ChipProps = {
  active?: boolean;
  label: string;
  sub?: string;
  onClick: () => void;
};

function Chip({ active, label, sub, onClick }: ChipProps) {
  return (
    <button
      type="button"
      className={`dash-chip${active ? " is-active" : ""}`}
      onClick={onClick}
      title={sub || label}
    >
      <span>{label}</span>
      {sub ? <small>{sub}</small> : null}
    </button>
  );
}

/** Voice + persona only — integrations live in IntegrationsPanel. */
export default function SettingsPanel() {
  const [opts, setOpts] = useState<SettingsOptions | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const s = await api.settings();
      setOpts(s);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const settings = opts?.settings;
  const patch = async (body: Record<string, unknown>) => {
    setBusy(true);
    setMsg("");
    try {
      const res = await api.setSettings(body);
      if (opts) setOpts({ ...opts, settings: res.settings });
      setMsg("Saved");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!opts || !settings) {
    return (
      <section className="amy-panel">
        <h2>Voice & persona</h2>
        <p className="amy-empty">{msg || "Loading…"}</p>
      </section>
    );
  }

  return (
    <section className="amy-panel">
      <div className="amy-panel__head">
        <h2>Voice & persona</h2>
        {msg ? <span className="dash-meta">{msg}</span> : null}
      </div>

      <div className="dash-settings-block">
        <h3>Voice</h3>
        <p className="dash-meta">HiveSTEAM Piper voice</p>
        <div className="dash-chips">
          {(opts.voice_presets || []).map((v) => (
            <Chip
              key={v.name}
              active={settings.voice_id === v.name}
              label={(v.name || "").replace(/^en_[A-Z]{2}-/, "").replace(/-/g, " ")}
              sub={v.quality || undefined}
              onClick={() => void patch({ voice_id: v.name })}
            />
          ))}
        </div>
        <p className="dash-meta">Style</p>
        <div className="dash-chips">
          {(opts.voice_styles || []).map((s) => (
            <Chip
              key={s}
              active={settings.voice_style === s}
              label={s}
              onClick={() => void patch({ voice_style: s })}
            />
          ))}
        </div>
      </div>

      <div className="dash-settings-block">
        <h3>Persona</h3>
        <p className="dash-meta">Tone presets</p>
        <div className="dash-chips">
          {(opts.persona_presets || []).map((p) => (
            <Chip
              key={p.id}
              active={settings.persona_preset === p.id}
              label={p.label}
              sub={p.blurb}
              onClick={() => void patch({ persona_preset: p.id })}
            />
          ))}
        </div>
        <p className="dash-meta">Clearance</p>
        <div className="dash-chips">
          {(opts.clearance_roles || []).map((r) => (
            <Chip
              key={r}
              active={settings.clearance_role === r}
              label={r}
              onClick={() => void patch({ clearance_role: r })}
            />
          ))}
        </div>
        <div className="dash-chips">
          {(opts.clearance_labels || []).map((l) => (
            <Chip
              key={l}
              active={settings.clearance_label === l}
              label={l}
              onClick={() => void patch({ clearance_label: l })}
            />
          ))}
        </div>
        {busy ? <p className="dash-meta">Saving…</p> : null}
      </div>
    </section>
  );
}
