import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, ClipboardList, Inbox, Play, RefreshCw, Search, ShieldAlert } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type AlertListItem, type AlertStatus } from "../api";
import { RunningOverlay } from "../components/RunningOverlay";
import { Avatar, RoutePill, Skeleton, Toast } from "../components/ui";
import { RULE_LABEL, shortDate } from "../lib/format";

type Filter = AlertStatus | "all";
const FILTERS: [Filter, string][] = [
  ["open", "Open"],
  ["in_review", "In review"],
  ["closed", "Closed"],
  ["all", "All"],
];
const STATUS_LABEL: Record<AlertStatus, string> = { open: "Open", in_review: "In review", closed: "Closed" };

export function QueuePage() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: api.alerts });
  const [filter, setFilter] = useState<Filter>("open");
  const [q, setQ] = useState("");
  const [rule, setRule] = useState("");
  const [error, setError] = useState<string | null>(null);

  const open = useMutation({
    mutationFn: api.openCase,
    onSuccess: (c) => {
      qc.setQueryData(["case", c.case_id], c);
      void qc.invalidateQueries({ queryKey: ["alerts"] });
      nav(`/cases/${c.case_id}`);
    },
    onError: (e) => setError(e.message),
  });

  const all = alerts.data ?? [];
  const counts = useMemo(() => {
    const c = { open: 0, in_review: 0, closed: 0, all: all.length, escalate: 0 };
    for (const a of all) {
      c[a.status]++;
      if (a.recommended_route === "escalate" && a.status !== "closed") c.escalate++;
    }
    return c;
  }, [all]);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return all.filter(
      (a) =>
        (filter === "all" || a.status === filter) &&
        (!rule || a.rule_id === rule) &&
        (!needle ||
          [a.alert_id, a.customer_name, a.customer_id, a.case_id ?? ""].some((s) =>
            s.toLowerCase().includes(needle),
          )),
    );
  }, [all, filter, q, rule]);

  const go = (a: AlertListItem) => {
    if (a.case_id) nav(`/cases/${a.case_id}`);
    else open.mutate(a.alert_id);
  };

  const stats = [
    { label: "Open alerts", value: counts.open, foot: "awaiting a first look", icon: Inbox, tone: "" },
    {
      label: "Recommended escalations",
      value: counts.escalate,
      foot: "prioritised to the top",
      icon: ShieldAlert,
      tone: "esc",
    },
    { label: "In review", value: counts.in_review, foot: "packs ready for a decision", icon: ClipboardList, tone: "info" },
    { label: "Closed", value: counts.closed, foot: "decided by an analyst", icon: CheckCircle2, tone: "ok" },
  ];

  return (
    <div className="fade-in">
      <div className="page-head">
        <div>
          <h1>Alert queue</h1>
          <p className="sub">Alerts the copilot recommends escalating come first. Every final call is yours.</p>
        </div>
        <div className="actions">
          <button className="btn" onClick={() => alerts.refetch()} disabled={alerts.isFetching}>
            <RefreshCw size={15} className={alerts.isFetching ? "spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      <div className="stats">
        {stats.map((s) => (
          <div className="card stat" key={s.label}>
            <span className={`icon-tile ${s.tone}`}>
              <s.icon size={17} />
            </span>
            <div>
              <div className="stat-label">{s.label}</div>
              <div className="stat-value">{alerts.isLoading ? <Skeleton h={28} w={48} /> : s.value}</div>
              <div className="stat-foot">{s.foot}</div>
            </div>
          </div>
        ))}
      </div>

      <section className="card">
        <div className="toolbar">
          <div className="segmented" role="tablist">
            {FILTERS.map(([f, label]) => (
              <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)} role="tab">
                {label}
                <span className="count">{counts[f]}</span>
              </button>
            ))}
          </div>
          <div className="search">
            <Search size={15} />
            <input
              className="input"
              placeholder="Search customer, alert or case…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <select className="input" style={{ width: "auto", height: 38 }} value={rule} onChange={(e) => setRule(e.target.value)}>
            <option value="">All rules</option>
            {Object.entries(RULE_LABEL).map(([id, label]) => (
              <option key={id} value={id}>
                {id} · {label}
              </option>
            ))}
          </select>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Customer</th>
                <th>Alert</th>
                <th>Rule</th>
                <th className="hide-sm">Window</th>
                <th>Status</th>
                <th>Copilot</th>
                <th>Final</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {alerts.isLoading &&
                Array.from({ length: 8 }, (_, i) => (
                  <tr key={i}>
                    {Array.from({ length: 8 }, (_, j) => (
                      <td key={j}>
                        <Skeleton h={14} w={j === 0 ? 160 : 70} />
                      </td>
                    ))}
                  </tr>
                ))}
              {rows.map((a) => (
                <tr key={a.alert_id} className="row-link" onClick={() => go(a)}>
                  <td>
                    <div className="cust">
                      <Avatar name={a.customer_name} />
                      <div>
                        <div className="cust-name">{a.customer_name}</div>
                        <div className="cust-id mono">{a.customer_id}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <div className="mono">{a.alert_id}</div>
                    {a.case_id && <div className="faint mono" style={{ fontSize: 12 }}>{a.case_id}</div>}
                  </td>
                  <td>
                    <div>{RULE_LABEL[a.rule_id] ?? a.rule_id}</div>
                    <div className="faint mono" style={{ fontSize: 12 }}>{a.rule_id}</div>
                  </td>
                  <td className="hide-sm muted" style={{ whiteSpace: "nowrap" }}>
                    {shortDate(a.window_start)} – {shortDate(a.window_end)}
                  </td>
                  <td>
                    <span className="pill">{STATUS_LABEL[a.status]}</span>
                  </td>
                  <td>
                    <RoutePill route={a.recommended_route} />
                  </td>
                  <td>
                    <RoutePill route={a.final_route} />
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {a.case_id ? (
                      <ArrowRight size={16} className="row-go" />
                    ) : (
                      <span className="btn btn-sm row-go" style={{ opacity: undefined }}>
                        <Play size={13} /> Run copilot
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {alerts.isError && (
            <div className="empty">
              <ShieldAlert size={28} />
              <p>Could not load alerts: {alerts.error.message}</p>
            </div>
          )}
          {alerts.isSuccess && rows.length === 0 && (
            <div className="empty">
              <Inbox size={28} />
              <p>No alerts match these filters.</p>
            </div>
          )}
        </div>
        {alerts.isSuccess && (
          <div className="table-foot">
            Showing {rows.length} of {all.length} alerts · click a row to open its case, or run the copilot on a new one
          </div>
        )}
      </section>

      {open.isPending && <RunningOverlay alertId={open.variables} />}
      {error && <Toast message={error} onClose={() => setError(null)} />}
    </div>
  );
}
