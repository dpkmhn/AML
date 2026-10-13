import { AlertTriangle, ArrowDownLeft, ArrowUpRight, CheckCircle2, CircleHelp, ShieldAlert, X } from "lucide-react";
import { Fragment, useEffect, useState, type ReactNode } from "react";
import type { Route, Txn } from "../api";
import { aed, initials, ROUTE_LABEL, txnTime } from "../lib/format";

export function RoutePill({ route, label }: { route: Route | null; label?: string }) {
  if (!route) return <span className="faint">-</span>;
  return (
    <span className={`pill ${route}`}>
      <span className="dot" />
      {label ?? ROUTE_LABEL[route]}
    </span>
  );
}

export const ROUTE_ICON: Record<Route, typeof ShieldAlert> = {
  escalate: ShieldAlert,
  needs_info: CircleHelp,
  close: CheckCircle2,
};

const HUES = [243, 262, 199, 172, 330, 24, 152, 210];

export function Avatar({ name, size }: { name: string; size?: "lg" }) {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  const hue = HUES[h % HUES.length]!;
  return (
    <span
      className={`avatar ${size ?? ""}`}
      style={{ background: `linear-gradient(135deg, hsl(${hue} 70% 58%), hsl(${hue + 28} 65% 48%))` }}
    >
      {initials(name)}
    </span>
  );
}

export function Card({
  title,
  icon,
  tone,
  right,
  children,
  className = "",
  body = true,
}: {
  title: string;
  icon: ReactNode;
  tone?: "esc" | "info" | "ok";
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  body?: boolean;
}) {
  return (
    <section className={`card ${className}`}>
      <header className="card-head">
        <span className={`icon-tile ${tone ?? ""}`}>{icon}</span>
        <h3>{title}</h3>
        {right && <div className="right">{right}</div>}
      </header>
      {body ? <div className="card-body">{children}</div> : children}
    </section>
  );
}

/** Text with every TXN-/CHK- id rendered as a chip; the text itself is never parsed as HTML. */
export function IdText({ text, onTxn }: { text: string; onTxn?: (id: string) => void }) {
  const parts = text.split(/\b((?:TXN|CHK)-[A-Z0-9-]+)\b/g);
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <span
            key={i}
            className={`tag ${onTxn && p.startsWith("TXN") ? "link" : ""}`}
            onClick={onTxn && p.startsWith("TXN") ? () => onTxn(p) : undefined}
          >
            {p}
          </span>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        ),
      )}
    </>
  );
}

/** KYC notes with each quoted span highlighted (case-insensitive exact match). */
export function Highlighted({ text, quotes }: { text: string; quotes: string[] }) {
  const lower = text.toLowerCase();
  const spans = quotes
    .map((q) => q.trim().replace(/^["'“]|["'”]$/g, ""))
    .filter(Boolean)
    .map((q) => {
      const i = lower.indexOf(q.toLowerCase());
      return i >= 0 ? ([i, i + q.length] as const) : null;
    })
    .filter((s): s is readonly [number, number] => s !== null)
    .sort((a, b) => a[0] - b[0]);
  const out: ReactNode[] = [];
  let pos = 0;
  for (const [a, b] of spans) {
    if (a < pos) continue;
    out.push(text.slice(pos, a), <mark key={a}>{text.slice(a, b)}</mark>);
    pos = b;
  }
  out.push(text.slice(pos));
  return <>{out}</>;
}

export function TxnTable({
  txns,
  highlight,
  limit = 6,
}: {
  txns: Txn[];
  highlight?: string | null;
  limit?: number;
}) {
  const [all, setAll] = useState(false);
  if (!txns.length) return <p className="faint">No transactions in the pack.</p>;
  // A highlighted transaction past the limit expands the table so it can be scrolled to
  const expanded = all || (!!highlight && txns.findIndex((t) => t.txn_id === highlight) >= limit);
  const shown = expanded ? txns : txns.slice(0, limit);
  return (
    <div className="inner-table table-wrap">
      <table className="txn-table">
        <thead>
          <tr>
            <th>Transaction</th>
            <th>Date</th>
            <th>Direction</th>
            <th className="num">Amount</th>
            <th>Counterparty</th>
            <th className="hide-sm">Reference</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((t) => (
            <tr
              key={t.txn_id}
              id={`txn-${t.txn_id}`}
              style={highlight === t.txn_id ? { background: "var(--accent-soft)" } : undefined}
            >
              <td>
                <span className="mono">{t.txn_id}</span>
              </td>
              <td className="muted nowrap">{txnTime(t.ts)}</td>
              <td className="nowrap">
                <span className={`dir ${t.direction}`}>
                  {t.direction === "in" ? <ArrowDownLeft size={14} /> : <ArrowUpRight size={14} />}
                  {t.direction === "in" ? "In" : "Out"}
                </span>
                <span className="faint"> · {t.channel}</span>
              </td>
              <td className="num" style={{ fontWeight: 600 }}>
                {aed(t.amount_aed, true)}
              </td>
              <td className="nowrap">
                {t.counterparty_name ?? <span className="faint">-</span>}
                {t.counterparty_country && <span className="tag" style={{ marginLeft: 6 }}>{t.counterparty_country}</span>}
              </td>
              <td className="hide-sm">
                <div className="ref" title={t.reference ?? ""}>
                  {t.reference ?? <span className="faint">-</span>}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {txns.length > limit && (
        <button className="table-more" onClick={() => setAll(!expanded)}>
          {expanded ? "Show fewer" : `Show all ${txns.length} transactions`}
        </button>
      )}
    </div>
  );
}

export function Toast({ message, onClose }: { message: string; onClose: () => void }) {
  useEffect(() => {
    const t = setTimeout(onClose, 8000);
    return () => clearTimeout(t);
  }, [message, onClose]);
  return (
    <div className="toast" role="alert">
      <AlertTriangle size={18} />
      <div style={{ flex: 1 }}>{message}</div>
      <button className="btn btn-ghost btn-sm icon-btn" onClick={onClose} aria-label="Dismiss">
        <X size={15} />
      </button>
    </div>
  );
}

export function Skeleton({ h = 16, w = "100%", r }: { h?: number; w?: number | string; r?: number }) {
  return <div className="skeleton" style={{ height: h, width: w, borderRadius: r }} />;
}
