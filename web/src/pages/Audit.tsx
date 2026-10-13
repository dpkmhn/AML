import { useQuery } from "@tanstack/react-query";
import { AlertOctagon, ArrowLeft, Bot, ChevronRight, Clock, Cpu, Database, Hash, ScrollText, UserCheck } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type AuditRow } from "../api";
import { Skeleton } from "../components/ui";
import { dateTime, stepLabel } from "../lib/format";

const kind = (r: AuditRow) => (r.step.includes("review") ? "human" : r.model ? "llm" : "");

export function AuditPage() {
  const { caseId = "" } = useParams();
  const q = useQuery({ queryKey: ["audit", caseId], queryFn: () => api.audit(caseId) });
  const [open, setOpen] = useState<number | null>(null);
  const rows = q.data ?? [];
  const maxLat = Math.max(1, ...rows.map((r) => r.latency_ms ?? 0));
  const sum = (k: "tokens_in" | "tokens_out" | "latency_ms") => rows.reduce((s, r) => s + (r[k] ?? 0), 0);
  const fmt = new Intl.NumberFormat("en");

  const stats = [
    { label: "Steps", value: rows.length, icon: Hash },
    { label: "Model calls", value: rows.filter((r) => r.model).length, icon: Bot },
    { label: "Tokens in / out", value: `${fmt.format(sum("tokens_in"))} / ${fmt.format(sum("tokens_out"))}`, icon: Cpu },
    { label: "Total step time", value: `${(sum("latency_ms") / 1000).toFixed(1)} s`, icon: Clock },
  ];

  return (
    <div className="fade-in" style={{ maxWidth: 1040 }}>
      <div className="crumbs">
        <Link to="/">Alert queue</Link>
        <ChevronRight size={14} />
        <Link to={`/cases/${caseId}`} className="mono">
          {caseId}
        </Link>
        <ChevronRight size={14} />
        <span>Audit trail</span>
      </div>
      <div className="page-head">
        <div>
          <h1>Audit trail</h1>
          <p className="sub">Every step of every run, with its model, prompt version, tokens and latency, in order.</p>
        </div>
        <div className="actions">
          <Link to={`/cases/${caseId}`} className="btn">
            <ArrowLeft size={15} /> Back to the case
          </Link>
        </div>
      </div>

      <div className="stats">
        {stats.map((s) => (
          <div className="card stat" key={s.label}>
            <span className="icon-tile">
              <s.icon size={17} />
            </span>
            <div>
              <div className="stat-label">{s.label}</div>
              <div className="stat-value" style={{ fontSize: 22 }}>
                {q.isLoading ? <Skeleton h={26} w={60} /> : s.value}
              </div>
            </div>
          </div>
        ))}
      </div>

      {q.isError && (
        <div className="card empty">
          <AlertOctagon size={28} />
          <p>{q.error.message}</p>
        </div>
      )}
      {q.isSuccess && rows.length === 0 && (
        <div className="card empty">
          <ScrollText size={28} />
          <p>No audit rows yet.</p>
        </div>
      )}

      <div className="timeline">
        {rows.map((r) => {
          const k = kind(r);
          const Icon = k === "human" ? UserCheck : k === "llm" ? Bot : Database;
          const isOpen = open === r.id;
          return (
            <div className="tl-item" key={r.id}>
              <div className={`tl-node ${k}`}>
                <Icon size={18} />
              </div>
              <div className="card tl-card">
                <button className="tl-head" onClick={() => setOpen(isOpen ? null : r.id)} aria-expanded={isOpen}>
                  <span className="tl-step">{stepLabel(r.step)}</span>
                  <span className="faint mono" style={{ fontSize: 12 }}>
                    #{r.id}
                  </span>
                  {r.model && <span className="pill needs_info">{r.model}</span>}
                  {r.prompt_version && <span className="pill mono">{r.prompt_version}</span>}
                  <span className="tl-meta">
                    {r.tokens_in != null && (
                      <span className="hide-sm">
                        {fmt.format(r.tokens_in)} → {fmt.format(r.tokens_out ?? 0)} tok
                      </span>
                    )}
                    {r.latency_ms != null && (
                      <>
                        <span className="lat hide-sm">
                          <span style={{ width: `${Math.max(3, (r.latency_ms / maxLat) * 100)}%` }} />
                        </span>
                        <span className="mono" style={{ minWidth: 56, textAlign: "right" }}>
                          {r.latency_ms >= 1000 ? `${(r.latency_ms / 1000).toFixed(1)} s` : `${r.latency_ms} ms`}
                        </span>
                      </>
                    )}
                    <ChevronRight size={15} style={{ transform: isOpen ? "rotate(90deg)" : undefined, transition: "transform .2s" }} />
                  </span>
                </button>
                {isOpen && (
                  <pre className="json fade-in">
                    <span className="faint">{dateTime(r.created_at)}</span>
                    {"\n"}
                    {JSON.stringify(r.output, null, 2)}
                  </pre>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
