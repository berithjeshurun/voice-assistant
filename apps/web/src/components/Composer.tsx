import { FormEvent, useState } from "react";
import FuseButton from "./reactbits/FuseButton";
import "./Composer.css";

type Props = {
  placeholder?: string;
  busy?: boolean;
  onSend: (text: string) => void;
  onWake?: () => void;
  onStop?: () => void;
};

/** Plain Amy composer — no model pickers, no fake “High” effort chrome. */
export default function Composer({
  placeholder = "Tell Amy what to do…",
  busy,
  onSend,
  onWake,
  onStop,
}: Props) {
  const [value, setValue] = useState("");

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const msg = value.trim();
    if (!msg || busy) return;
    onSend(msg);
    setValue("");
  };

  return (
    <form className="amy-composer" onSubmit={submit}>
      <input
        className="amy-composer__input"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder}
        disabled={busy}
        autoComplete="off"
        aria-label="Message Amy"
      />
      <div className="amy-composer__actions">
        {onWake ? (
          <button type="button" className="amy-composer__ghost" onClick={onWake} disabled={busy}>
            Wake
          </button>
        ) : null}
        {busy && onStop ? (
          <button type="button" className="amy-composer__stop" onClick={onStop}>
            Stop
          </button>
        ) : (
          <FuseButton
            label={busy ? "…" : "Send"}
            disabled={busy || !value.trim()}
            onCommit={() => submit()}
          />
        )}
      </div>
    </form>
  );
}
