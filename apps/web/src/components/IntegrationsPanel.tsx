import { useEffect, useMemo, useState } from "react";
import { api, IntegrationInfo } from "../api";
import FuseButton from "./reactbits/FuseButton";
import SquishSwitch from "./reactbits/SquishSwitch";
import "./IntegrationsPanel.css";

const PAGE = 6;

export default function IntegrationsPanel() {
  const [items, setItems] = useState<IntegrationInfo[]>([]);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [keyDraft, setKeyDraft] = useState<Record<string, Record<string, string>>>({});
  const [enabledOnly, setEnabledOnly] = useState(false);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const res = await api.integrations();
      const list = res.integrations || [];
      setItems(list);
      if (!selected && list[0]) setSelected(list[0].id);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter((it) => {
      if (enabledOnly && !it.ready) return false;
      if (!q) return true;
      const hay = `${it.id} ${it.name} ${it.kind || ""} ${it.pack || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [items, query, enabledOnly]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE));
  const safePage = Math.min(page, pageCount - 1);
  const slice = filtered.slice(safePage * PAGE, safePage * PAGE + PAGE);
  const active = items.find((it) => it.id === selected) || null;

  useEffect(() => {
    setPage(0);
  }, [query, enabledOnly]);

  const saveKeys = async (id: string) => {
    setBusy(true);
    setMsg("");
    try {
      await api.setIntegration(id, keyDraft[id] || {});
      setKeyDraft((d) => ({ ...d, [id]: {} }));
      await load();
      setMsg(`${id} saved`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="integ amy-panel">
      <div className="amy-panel__head">
        <h2>Integrations</h2>
        <span className="dash-meta">{filtered.length} of {items.length}</span>
      </div>
      <p className="dash-meta">
        Dynamic catalog — search & page so a long list never floods the screen. Keys stay local.
      </p>

      <div className="integ__toolbar">
        <input
          className="integ__search"
          type="search"
          placeholder="Search integrations…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <SquishSwitch
          checked={enabledOnly}
          onChange={setEnabledOnly}
          label="Ready only"
          ariaLabel="Show ready integrations only"
        />
      </div>

      <div className="integ__layout">
        <div className="integ__list">
          {slice.map((it) => (
            <button
              key={it.id}
              type="button"
              className={`integ__row${selected === it.id ? " is-active" : ""}`}
              onClick={() => setSelected(it.id)}
            >
              <strong>{it.name || it.id}</strong>
              <span data-ready={it.ready}>{it.ready ? "ready" : "needs keys"}</span>
              {it.kind ? <small>{it.kind}</small> : null}
            </button>
          ))}
          {slice.length === 0 ? <p className="amy-empty">No matches.</p> : null}

          <div className="integ__pager">
            <button
              type="button"
              className="ghost"
              disabled={safePage <= 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              Prev
            </button>
            <span className="dash-meta">
              {safePage + 1} / {pageCount}
            </span>
            <button
              type="button"
              className="ghost"
              disabled={safePage >= pageCount - 1}
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
            >
              Next
            </button>
          </div>
        </div>

        <div className="integ__detail">
          {!active ? (
            <p className="amy-empty">Select an integration.</p>
          ) : (
            <>
              <h3>{active.name}</h3>
              <p className="dash-meta">
                {active.id}
                {active.pack ? ` · pack ${active.pack}` : ""}
                {active.docs ? ` · ${active.docs}` : ""}
              </p>
              <div className="integ__keys">
                {(active.keys || []).map((k) => (
                  <label key={k}>
                    <span>
                      {k}
                      {active.configured?.[k] ? " · set" : ""}
                    </span>
                    <input
                      type="password"
                      autoComplete="off"
                      placeholder={active.configured?.[k] ? "••••••••" : "paste key"}
                      value={keyDraft[active.id]?.[k] || ""}
                      disabled={busy}
                      onChange={(e) =>
                        setKeyDraft((d) => ({
                          ...d,
                          [active.id]: { ...(d[active.id] || {}), [k]: e.target.value },
                        }))
                      }
                    />
                  </label>
                ))}
                {(active.keys || []).length === 0 ? (
                  <p className="amy-empty">No secret keys required.</p>
                ) : null}
              </div>
              <FuseButton
                label={`Save ${active.name}`}
                disabled={busy}
                onCommit={() => void saveKeys(active.id)}
              />
            </>
          )}
          {msg ? <p className="dash-meta">{msg}</p> : null}
        </div>
      </div>
    </section>
  );
}
