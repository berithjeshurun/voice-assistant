import "./PillNav.css";

export type PillItem = { id: string; label: string };

type Props = {
  items: PillItem[];
  active: string;
  onChange: (id: string) => void;
};

/** React Bits–inspired pill navigation. */
export default function PillNav({ items, active, onChange }: Props) {
  return (
    <nav className="rb-pillnav" aria-label="Config sections">
      {items.map((it) => (
        <button
          key={it.id}
          type="button"
          className={`rb-pillnav__item${active === it.id ? " is-active" : ""}`}
          onClick={() => onChange(it.id)}
        >
          {it.label}
        </button>
      ))}
    </nav>
  );
}
