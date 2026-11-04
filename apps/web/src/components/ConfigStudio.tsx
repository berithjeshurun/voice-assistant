import { useEffect, useMemo, useState } from "react";
import { api, ConfigField, ConfigStudioPayload } from "../api";
import FuseButton from "./reactbits/FuseButton";
import ScrubField from "./reactbits/ScrubField";
import SquishSwitch from "./reactbits/SquishSwitch";
import "./ConfigStudio.css";

export default function ConfigStudio() {
  const [data, setData] = useState<ConfigStudioPayload | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [section, setSection] = useState("home");
  const [apps, setApps] = useState<string[]>([]);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [query, setQuery] = useState("");

  const load = async () => {
    try {
      const res = await api.configStudio();
      setData(res);
      const vals: Record<string, unknown> = {};
      for (const f of res.fields || []) vals[f.id] = f.value;
      setDraft(vals);
      setApps(res.apps_enabled || []);
      setSection(res.sections?.[0]?.id || "home");
      setDirty(false);
      setMsg("");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const q = query.trim().toLowerCase();

  const fields = useMemo(() => {
    const all = data?.fields || [];
    if (q) {
      return all.filter((f) => {
        const hay = `${f.id} ${f.label} ${f.path} ${f.section}`.toLowerCase();
        return hay.includes(q);
      });
    }
    return all.filter((f) => f.section === section);
  }, [data, section, q]);

  const sectionMeta = data?.sections?.find((s) => s.id === section);
  const fieldCount = data?.fields?.length ?? 0;

  const setField = (id: string, value: unknown) => {
    setDraft((d) => ({ ...d, [id]: value }));
    setDirty(true);
  };

  const save = async () => {
    setBusy(true);
    setMsg("");
    try {
      const res = await api.saveConfigStudio({ values: draft, apps_enabled: apps });
      setData(res);
      const vals: Record<string, unknown> = {};
      for (const f of res.fields || []) vals[f.id] = f.value;
      setDraft(vals);
      setApps(res.apps_enabled || []);
      setDirty(false);
      setMsg("Saved — restart Amy for assemble/agent changes to fully apply.");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!data) {
    return (
      <section className="config-studio amy-panel">
        <h2>Config Studio</h2>
        <p className="amy-empty">{msg || "Loading 1:1 config…"}</p>
      </section>
    );
  }

  return (
    <section className="config-studio amy-panel">
      <header className="config-studio__head">
        <div>
          <h2>Config Studio</h2>
          <p className="dash-meta">
            1:1 with hive.yaml · {fieldCount} fields · <code>{data.path}</code>
          </p>
        </div>
        <div className="config-studio__actions">
          <FuseButton
            label={busy ? "Working…" : dirty ? "Save changes" : "Saved"}
            disabled={busy || !dirty}
            onCommit={() => void save()}
            settle="reset"
          />
        </div>
      </header>

      <div className="config-studio__toolbar">
        <input
          className="config-studio__search"
          type="search"
          placeholder="Search every setting…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoComplete="off"
        />
        <span className="dash-meta">
          {q ? `${fields.length} matches` : `${fields.length} in section`}
        </span>
      </div>

      {!q ? (
        <div className="config-studio__rail" role="tablist" aria-label="Config sections">
          {(data.sections || []).map((s) => (
            <button
              key={s.id}
              type="button"
              role="tab"
              aria-selected={section === s.id}
              className={`config-sec${section === s.id ? " is-active" : ""}`}
              onClick={() => setSection(s.id)}
            >
              {s.label}
            </button>
          ))}
        </div>
      ) : null}

      {!q && sectionMeta ? (
        <p className="config-studio__blurb">{sectionMeta.blurb}</p>
      ) : null}
      {msg ? <p className="dash-meta">{msg}</p> : null}

      <div className="config-studio__grid">
        {fields.map((f) => (
          <FieldCard
            key={f.id}
            field={f}
            value={draft[f.id]}
            onChange={(v) => setField(f.id, v)}
            disabled={busy}
          />
        ))}
        {fields.length === 0 ? <p className="amy-empty">No fields match.</p> : null}
      </div>

      {section === "amy" || section === "amy:apps" ? (
        <div className="config-studio__apps">
          <h3>App packs</h3>
          <p className="dash-meta">Also manageable from Workspace</p>
          <div className="config-studio__pack-list">
            {(data.packs_available || []).map((pid) => {
              const on = apps.includes(pid);
              return (
                <SquishSwitch
                  key={pid}
                  checked={on}
                  label={pid}
                  disabled={busy}
                  onChange={(next) => {
                    setApps((prev) =>
                      next
                        ? Array.from(new Set([...prev, pid]))
                        : prev.filter((x) => x !== pid),
                    );
                    setDirty(true);
                  }}
                />
              );
            })}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function FieldCard({
  field,
  value,
  onChange,
  disabled,
}: {
  field: ConfigField;
  value: unknown;
  onChange: (v: unknown) => void;
  disabled?: boolean;
}) {
  const wide = field.type === "longtext" || field.type === "json" || field.type === "list";
  const listText =
    field.type === "list"
      ? Array.isArray(value)
        ? (value as unknown[]).map(String).join("\n")
        : value == null
          ? ""
          : String(value)
      : "";
  const jsonText =
    field.type === "json"
      ? typeof value === "string"
        ? value
        : JSON.stringify(value ?? null, null, 2)
      : "";

  return (
    <div className={`config-field${wide ? " config-field--wide" : ""}`}>
      <div className="config-field__top">
        <div>
          <strong>{field.label}</strong>
          <p className="dash-meta config-field__path">{field.path || field.blurb}</p>
        </div>
        {field.type === "toggle" ? (
          <SquishSwitch
            checked={Boolean(value)}
            onChange={(v) => onChange(v)}
            disabled={disabled}
          />
        ) : null}
      </div>

      {field.type === "text" || field.type === "password" ? (
        <input
          className="config-field__input"
          type={field.type === "password" ? "password" : "text"}
          value={value == null ? "" : String(value)}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          autoComplete="off"
        />
      ) : null}

      {field.type === "number" ? (
        <ScrubField
          value={typeof value === "number" ? value : Number(value) || 0}
          onChange={(n) => onChange(n)}
          disabled={disabled}
        />
      ) : null}

      {field.type === "longtext" ? (
        <textarea
          className="config-field__textarea"
          rows={8}
          value={value == null ? "" : String(value)}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          spellCheck={false}
        />
      ) : null}

      {field.type === "list" ? (
        <textarea
          className="config-field__textarea"
          rows={5}
          value={listText}
          disabled={disabled}
          placeholder="one item per line"
          onChange={(e) =>
            onChange(
              e.target.value
                .split(/\r?\n/)
                .map((s) => s.trim())
                .filter(Boolean),
            )
          }
          spellCheck={false}
        />
      ) : null}

      {field.type === "json" ? (
        <textarea
          className="config-field__textarea config-field__textarea--mono"
          rows={10}
          value={jsonText}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          spellCheck={false}
        />
      ) : null}

      {field.type === "select" ? (
        <div className="config-field__options">
          {(field.options || []).map((opt) => {
            const active = String(value) === String(opt);
            return (
              <button
                key={String(opt)}
                type="button"
                className={`config-opt${active ? " is-active" : ""}`}
                disabled={disabled}
                onClick={() => onChange(opt)}
              >
                {String(opt)}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
