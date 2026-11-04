import { useEffect, useState } from "react";
import { api, ApprovalRequest, GuardStatus } from "../api";

type Props = {
  approvals: ApprovalRequest[];
  guard?: GuardStatus;
  onError?: (msg: string) => void;
  /** Approving actions and leaving lockdown need the admin role on the host. */
  canApprove?: boolean;
};

export function secondsLeft(expiresAt: number, now: number): number {
  return Math.max(0, Math.round(expiresAt - now / 1000));
}

export default function GuardPanel({ approvals, guard, onError, canApprove = true }: Props) {
  const [now, setNow] = useState(Date.now());
  const [sent, setSent] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!approvals.length) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [approvals.length]);

  const answer = (id: string, approve: boolean) => {
    setSent((s) => ({ ...s, [id]: true }));
    void api
      .approve(id, approve)
      .then((r) => {
        if (!r.ok) onError?.(r.error || "approval expired");
      })
      .catch((e) => {
        setSent((s) => ({ ...s, [id]: false }));
        onError?.(e instanceof Error ? e.message : String(e));
      });
  };

  const toggleLock = () => {
    const next = !guard?.lockdown;
    if (next || window.confirm("Leave lockdown and allow Amy to act again?")) {
      void api
        .lockdown(next)
        .catch((e) => onError?.(e instanceof Error ? e.message : String(e)));
    }
  };

  const lockDisabled = Boolean(guard?.lockdown) && !canApprove;

  return (
    <section className="guard" data-lockdown={guard?.lockdown ? "1" : "0"}>
      <div className="guard__bar">
        <span className="guard__mode">
          {guard?.enabled === false
            ? "GUARD OFF"
            : guard?.lockdown
              ? "LOCKDOWN"
              : `GUARD ${(guard?.mode || "standard").toUpperCase()}`}
        </span>
        <button
          type="button"
          className="guard__lock"
          onClick={toggleLock}
          disabled={lockDisabled}
          title={lockDisabled ? "Only an admin device can leave lockdown" : undefined}
        >
          {guard?.lockdown ? "Unlock" : "Lock"}
        </button>
      </div>
      {approvals.map((a) => (
        <div key={a.id} className="guard__ask" data-risk={a.risk}>
          <header>
            <span>APPROVAL · {a.tool}</span>
            <time>{secondsLeft(a.expires_at, now)}s</time>
          </header>
          <p className="guard__summary">{a.summary}</p>
          <p className="guard__reason">{a.reason}</p>
          {canApprove ? (
            <div className="guard__actions">
              <button type="button" disabled={sent[a.id]} onClick={() => answer(a.id, false)}>
                Deny
              </button>
              <button
                type="button"
                className="guard__approve"
                disabled={sent[a.id]}
                onClick={() => answer(a.id, true)}
              >
                Approve
              </button>
            </div>
          ) : (
            <p className="guard__reason">Waiting for approval on the host or an admin device.</p>
          )}
        </div>
      ))}
    </section>
  );
}
