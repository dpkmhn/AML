import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertOctagon,
  BookOpen,
  ChevronRight,
  CircleDot,
  FileSearch,
  FileText,
  Fingerprint,
  Gavel,
  History,
  Info,
  Layers,
  Loader2,
  Quote,
  ScrollText,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  UserRound,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type CaseDetail, type Finding, type Pack, type Route, type Txn } from "../api";
import {
  Avatar,
  Card,
  Highlighted,
  IdText,
  ROUTE_ICON,
  RoutePill,
  Skeleton,
  Toast,
  TxnTable,
} from "../components/ui";
import { aed, compactAed, date, dateTime, pct, ROUTE_LABEL, RULE_LABEL, TYPOLOGY_LABEL } from "../lib/format";

export function CasePage() {
  const { caseId = "" } = useParams();
  const q = useQuery({ queryKey: ["case", caseId], queryFn: () => api.case(caseId) });
  const [focusTxn, setFocusTxn] = useState<string | null>(null);

  const onTxn = useCallback((id: string) => {
    setFocusTxn(id);
    document.getElementById(`txn-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  if (q.isLoading) return <CaseSkeleton />;
  if (q.isError)
    return (
      <div className="card empty">
        <AlertOctagon size={28} />
        <p>{q.error.message}</p>
        <Link className="btn" to="/" style={{ marginTop: 14 }}>
          Back to the queue
        </Link>
      </div>
    );

  const c = q.data!;
  const pack = c.pack;
  if (!pack)
    return (
      <div className="card empty">
        <TriangleAlert size={28} />
        <p>{c.case_id} did not reach the review step. Open it again from the queue.</p>
      </div>
    );

  return (
    <div className="fade-in">
      <div className="crumbs">
        <Link to="/">Alert queue</Link>
        <ChevronRight size={14} />
        <span className="mono">{c.case_id}</span>
      </div>

      <div className="case-grid">
        <div className="stack">
          <Hero c={c} pack={pack} />
          {pack.flagged_references.length > 0 && <Flagged pack={pack} />}
          {c.status === "decided" && <Narrative c={c} />}
          <Findings pack={pack} txns={c.evidence_txns} />
          {pack.assessment && <AssessmentCard pack={pack} onTxn={onTxn} />}
          <Kyc pack={pack} />
          <Card
            title="Evidence transactions"
            icon={<Layers size={15} />}
            right={<span className="faint">{c.evidence_txns.length} cited in the pack</span>}
          >
            <TxnTable txns={c.evidence_txns} highlight={focusTxn} limit={8} />
          </Card>
          <Guidance pack={pack} content={c.guidance_content} />
        </div>

        <aside className="rail">
          <Recommendation pack={pack} />
          {c.status === "awaiting_review" ? <DecisionForm c={c} /> : <DecisionResult c={c} />}
        </aside>
      </div>
    </div>
  );
}

function Hero({ c, pack }: { c: CaseDetail; pack: Pack }) {
  const { customer: cu, alert: a, summary: s } = pack;
  const flowTotal = s.inflow_aed + s.outflow_aed || 1;
  return (
    <section className="card hero-card">
      <div className="hero">
        <Avatar name={cu.full_name} size="lg" />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <h1>{cu.full_name}</h1>
            <span className={`pill ${cu.risk_rating === "high" ? "escalate" : cu.risk_rating === "medium" ? "needs_info" : ""}`}>
              {cu.risk_rating} risk
            </span>
            {cu.is_pep && <span className="pill escalate">PEP</span>}
          </div>
          <p className="muted" style={{ marginTop: 2 }}>
            {cu.occupation} · <span style={{ textTransform: "capitalize" }}>{cu.segment}</span> · customer since{" "}
            {date(cu.account_opened)}
          </p>
          <div className="hero-meta">
            <span className="pill accent">
              <Fingerprint size={13} /> {a.rule_id} · {RULE_LABEL[a.rule_id] ?? "rule"}
            </span>
            <span className="tag">{a.alert_id}</span>
            <span className="tag">{cu.customer_id}</span>
            <span className="pill">
              Window {date(a.window_start)} – {date(a.window_end)}
            </span>
          </div>
        </div>
        <Link to={`/cases/${c.case_id}/audit`} className="btn btn-sm">
          <History size={14} /> Audit trail
        </Link>
      </div>
      <div className="kv-grid">
        <div className="kv">
          <div className="kv-label">Declared income</div>
          <div className="kv-value">{aed(cu.declared_monthly_income_aed)}</div>
          <div className="kv-sub">per month · baseline in {compactAed(s.baseline_monthly_inflow_aed)}</div>
        </div>
        <div className="kv">
          <div className="kv-label">Flow in review</div>
          <div className="kv-value nowrap" style={{ fontSize: 14 }}>
            <span style={{ color: "var(--ok)" }}>in {compactAed(s.inflow_aed).slice(4)}</span>
            <span className="faint"> / </span>
            <span style={{ color: "var(--esc)" }}>out {compactAed(s.outflow_aed).slice(4)}</span>
          </div>
          <div className="flow">
            <span style={{ width: `${(s.inflow_aed / flowTotal) * 100}%` }} />
            <span style={{ width: `${(s.outflow_aed / flowTotal) * 100}%` }} />
          </div>
        </div>
        <div className="kv">
          <div className="kv-label">Transactions</div>
          <div className="kv-value">{s.txn_count}</div>
          <div className="kv-sub">cash share {pct(s.cash_share)}</div>
        </div>
        <div className="kv">
          <div className="kv-label">Largest single</div>
          <div className="kv-value">{compactAed(s.max_single_txn_aed)}</div>
          <div className="kv-sub">
            {date(s.review_start)} – {date(s.review_end)}
          </div>
        </div>
      </div>
      <div className="card-body" style={{ borderTop: "1px solid var(--border)", fontSize: 13 }}>
        <span className="faint">Expected activity: </span>
        {cu.expected_activity}
      </div>
    </section>
  );
}

function Flagged({ pack }: { pack: Pack }) {
  return (
    <Card
      title="Flagged payment references"
      icon={<TriangleAlert size={15} />}
      tone="esc"
      className="flagged"
      right={<span className="pill escalate">{pack.flagged_references.length} flagged</span>}
    >
      <p className="muted" style={{ fontSize: 13 }}>
        Customer-written text that reads like an instruction. It reached the model only as quoted data, and the route
        was decided by rules.
      </p>
      {pack.flagged_references.map((f) => (
        <div key={f.txn_id} style={{ marginTop: 12 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span className="tag">{f.txn_id}</span>
            <span style={{ fontSize: 12.5, color: "var(--esc)", fontWeight: 600 }}>{f.note}</span>
          </div>
          <div className="untrusted">{f.reference ?? ""}</div>
        </div>
      ))}
    </Card>
  );
}

function scoreColor(f: Finding, explained: boolean) {
  if (explained) return "var(--ok)";
  if (f.score >= 0.7) return "var(--esc)";
  if (f.score >= 0.4) return "var(--info)";
  return "var(--accent)";
}

function Findings({ pack, txns }: { pack: Pack; txns: Txn[] }) {
  const byId = useMemo(() => new Map(txns.map((t) => [t.txn_id, t])), [txns]);
  const explained = new Set(pack.route.explained_typologies);
  const fired = pack.findings.filter((f) => f.score > 0).sort((a, b) => b.score - a.score);
  const quiet = pack.findings.filter((f) => f.score === 0);
  const [open, setOpen] = useState<string | null>(fired[0]?.typology ?? null);

  return (
    <Card
      title="Typology findings"
      icon={<FileSearch size={15} />}
      body={false}
      right={<span className="faint">deterministic rules · {fired.length} fired</span>}
    >
      {fired.length === 0 && <div className="card-body faint">No typology scored above zero.</div>}
      {fired.map((f) => {
        const isOpen = open === f.typology;
        const isExplained = explained.has(f.typology);
        const color = scoreColor(f, isExplained);
        return (
          <div key={f.typology} className={`finding ${isOpen ? "open" : ""}`}>
            <button className="finding-head" onClick={() => setOpen(isOpen ? null : f.typology)} aria-expanded={isOpen}>
              <span className="finding-name">
                {TYPOLOGY_LABEL[f.typology]}
                <span>
                  {isExplained ? (
                    <span className="pill close" style={{ height: 20, fontSize: 11 }}>
                      explained
                    </span>
                  ) : (
                    <span className="faint" style={{ fontSize: 12, fontWeight: 500 }}>
                      {f.evidence_txn_ids.length} transactions
                    </span>
                  )}
                </span>
              </span>
              <div className="score-bar">
                <span style={{ width: `${f.score * 100}%`, background: color }} />
              </div>
              <span className="score-num" style={{ color }}>
                {f.score.toFixed(2)}
              </span>
              <ChevronRight size={16} className="chev" />
            </button>
            {isOpen && (
              <div className="finding-body fade-in">
                <p className="finding-expl">{f.rule_explanation}</p>
                <TxnTable txns={f.evidence_txn_ids.map((i) => byId.get(i)).filter((t): t is Txn => !!t)} />
              </div>
            )}
          </div>
        );
      })}
      {quiet.length > 0 && (
        <div className="finding-quiet">
          Not triggered:
          {quiet.map((f) => (
            <span key={f.typology} className="pill" title={f.rule_explanation}>
              {TYPOLOGY_LABEL[f.typology]}
            </span>
          ))}
        </div>
      )}
    </Card>
  );
}

function AssessmentCard({ pack, onTxn }: { pack: Pack; onTxn: (id: string) => void }) {
  const a = pack.assessment!;
  return (
    <Card
      title="Copilot assessment"
      icon={<Sparkles size={15} />}
      tone="info"
      right={<span className="faint">LLM · explains, does not decide</span>}
    >
      <div className="section-label">Activity</div>
      <p className="prose">
        <IdText text={a.activity_summary} onTxn={onTxn} />
      </p>

      {a.concerns.length > 0 && (
        <>
          <div className="section-label">Concerns</div>
          {a.concerns.map((c, i) => (
            <div className="concern" key={i}>
              <CircleDot size={15} />
              <div>
                <IdText text={c} onTxn={onTxn} />
              </div>
            </div>
          ))}
        </>
      )}

      <div className="section-label">Benign explanations</div>
      {a.benign_explanations.length === 0 && <p className="faint">None offered.</p>}
      {a.benign_explanations.map((b, i) => (
        <div className="benign" key={i}>
          <div className="benign-title">
            <ShieldCheck size={16} />
            {TYPOLOGY_LABEL[b.typology]}
          </div>
          <p style={{ fontSize: 13.5 }}>
            <IdText text={b.explanation} onTxn={onTxn} />
          </p>
          {b.kyc_quote && (
            <blockquote className="quote">
              <Quote size={12} style={{ marginRight: 6, color: "var(--info)" }} />
              {b.kyc_quote}
            </blockquote>
          )}
          {(b.evidence_txn_ids.length > 0 || b.cited_chunk_ids.length > 0) && (
            <div className="chips">
              {b.evidence_txn_ids.map((t) => (
                <span key={t} className="tag link" onClick={() => onTxn(t)}>
                  {t}
                </span>
              ))}
              {b.cited_chunk_ids.map((c) => (
                <span key={c} className="tag" style={{ background: "var(--accent-soft)", color: "var(--accent-text)" }}>
                  {c}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}

      <div className="section-label">Missing information</div>
      {a.missing_information.length === 0 && <p className="faint">None.</p>}
      {a.missing_information.map((m, i) => (
        <div className="missing" key={i}>
          <Info size={15} style={{ flex: "none", marginTop: 3, color: "var(--text-3)" }} />
          <span style={{ flex: 1 }}>
            <IdText text={m.item} onTxn={onTxn} />
          </span>
          {m.changes_decision && <span className="pill needs_info">would change the decision</span>}
        </div>
      ))}
    </Card>
  );
}

function Kyc({ pack }: { pack: Pack }) {
  const quotes = (pack.assessment?.benign_explanations ?? []).map((b) => b.kyc_quote).filter((q): q is string => !!q);
  return (
    <Card
      title="KYC notes"
      icon={<UserRound size={15} />}
      right={quotes.length > 0 && <span className="pill needs_info">{quotes.length} quoted</span>}
    >
      <div className="kyc">
        {pack.customer.kyc_notes ? (
          <Highlighted text={pack.customer.kyc_notes} quotes={quotes} />
        ) : (
          <span className="faint">(none)</span>
        )}
      </div>
      {quotes.length > 0 && <p className="hint" style={{ marginTop: 8 }}>Highlighted words are quoted verbatim by the copilot and checked by code.</p>}
    </Card>
  );
}

function Guidance({ pack, content }: { pack: Pack; content: Record<string, string> }) {
  const items = [...pack.guidance].sort((a, b) => Number(b.cited) - Number(a.cited));
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Card
      title="Retrieved guidance"
      icon={<BookOpen size={15} />}
      body={false}
      right={<span className="faint">{items.filter((g) => g.cited).length} cited of {items.length}</span>}
    >
      {items.map((g) => {
        const isOpen = open === g.chunk_id;
        return (
          <div key={g.chunk_id} className={`acc ${isOpen ? "open" : ""}`}>
            <button className="acc-head" onClick={() => setOpen(isOpen ? null : g.chunk_id)} aria-expanded={isOpen}>
              <ChevronRight size={15} className="chev" />
              <span className="tag">{g.chunk_id}</span>
              <span style={{ fontWeight: 550 }}>{g.section}</span>
              <span className="faint hide-sm" style={{ fontSize: 12.5 }}>
                {g.typology.replace(/_/g, " ")}
              </span>
              {g.cited && (
                <span className="pill accent" style={{ marginLeft: "auto" }}>
                  cited
                </span>
              )}
            </button>
            {isOpen && <div className="acc-body fade-in">{content[g.chunk_id] ?? "No text stored."}</div>}
          </div>
        );
      })}
    </Card>
  );
}

function Recommendation({ pack }: { pack: Pack }) {
  const r = pack.route;
  const Icon = ROUTE_ICON[r.route];
  const confidence = pack.assessment?.confidence;
  return (
    <section className={`card rec ${r.route}`}>
      <div className="rec-top">
        <div className="rec-eyebrow">Copilot recommends</div>
        <div className="rec-route">
          <Icon size={24} />
          {ROUTE_LABEL[r.route]}
        </div>
        <div className="chips" style={{ marginTop: 8 }}>
          {r.rule_ids.map((id) => (
            <span key={id} className="tag">
              rule {id}
            </span>
          ))}
        </div>
      </div>
      <ul className="rec-reasons">
        {r.reasons.map((reason, i) => (
          <li key={i}>
            <ChevronRight size={13} />
            <span>{reason}</span>
          </li>
        ))}
      </ul>
      {confidence !== undefined && (
        <div className="gauge">
          Model confidence
          <div className="gauge-bar">
            <span style={{ width: `${confidence * 100}%` }} />
          </div>
          <b style={{ color: "var(--text)" }}>{confidence.toFixed(2)}</b>
        </div>
      )}
      {pack.assessment_errors.length > 0 && (
        <div style={{ padding: "0 20px 16px" }}>
          <div className="callout info" style={{ fontSize: 12.5 }}>
            <TriangleAlert size={15} />
            <div>Post-checks still failing after the retry: {pack.assessment_errors.join("; ")}</div>
          </div>
        </div>
      )}
    </section>
  );
}

const ROUTES: Route[] = ["escalate", "needs_info", "close"];
const REVIEWER_KEY = "aml.reviewer";

function DecisionForm({ c }: { c: CaseDetail }) {
  const qc = useQueryClient();
  const recommended = c.recommended_route ?? c.pack!.route.route;
  const [route, setRoute] = useState<Route>(recommended);
  const [reviewer, setReviewer] = useState(() => {
    try {
      return localStorage.getItem(REVIEWER_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const overriding = route !== recommended;
  const blocked = !reviewer.trim() || (overriding && !reason.trim());

  const submit = useMutation({
    mutationFn: () =>
      api.review(c.case_id, {
        reviewer: reviewer.trim(),
        final_route: route,
        override_reason: reason.trim() || null,
      }),
    onSuccess: () => {
      try {
        localStorage.setItem(REVIEWER_KEY, reviewer.trim());
      } catch {
        /* storage blocked */
      }
      void qc.invalidateQueries({ queryKey: ["case", c.case_id] });
      void qc.invalidateQueries({ queryKey: ["alerts"] });
    },
    onError: (e) => setError(e.message),
  });

  return (
    <section className="card">
      <header className="card-head">
        <span className="icon-tile">
          <Gavel size={15} />
        </span>
        <h3>Your decision</h3>
      </header>
      <form
        className="card-body"
        style={{ display: "flex", flexDirection: "column", gap: 16 }}
        onSubmit={(e) => {
          e.preventDefault();
          if (!blocked) submit.mutate();
        }}
      >
        <div className="route-choices" role="radiogroup" aria-label="Route">
          {ROUTES.map((r) => {
            const Icon = ROUTE_ICON[r];
            return (
              <button
                type="button"
                key={r}
                role="radio"
                aria-checked={route === r}
                className={`route-choice ${r} ${route === r ? "on" : ""}`}
                onClick={() => setRoute(r)}
              >
                <span className="radio" />
                <Icon size={16} style={{ color: `var(--${r === "escalate" ? "esc" : r === "close" ? "ok" : "info"})` }} />
                <span className="rc-title">{ROUTE_LABEL[r]}</span>
                {r === recommended && <span className="rc-badge">recommended</span>}
              </button>
            );
          })}
        </div>
        <div className="field">
          <label htmlFor="reviewer">Reviewer</label>
          <input
            id="reviewer"
            className="input"
            placeholder="Your name"
            value={reviewer}
            onChange={(e) => setReviewer(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="reason">
            Reason {overriding ? <span style={{ color: "var(--info)" }}>(required to override)</span> : <span className="faint">(optional)</span>}
          </label>
          <textarea
            id="reason"
            className="textarea"
            placeholder={overriding ? `Why ${ROUTE_LABEL[route]} rather than ${ROUTE_LABEL[recommended]}?` : "Notes for the narrative"}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          {overriding && !reason.trim() && (
            <span className="hint warn">You are overriding the recommendation. Give a reason.</span>
          )}
        </div>
        <button className="btn btn-primary btn-block" type="submit" disabled={blocked || submit.isPending}>
          {submit.isPending ? (
            <>
              <Loader2 size={16} className="spin" /> Writing the narrative…
            </>
          ) : (
            <>
              <Gavel size={16} /> Submit decision
            </>
          )}
        </button>
        <p className="hint" style={{ textAlign: "center" }}>
          The narrative is drafted from your decision and every step is written to the audit trail.
        </p>
      </form>
      {error && <Toast message={error} onClose={() => setError(null)} />}
    </section>
  );
}

function DecisionResult({ c }: { c: CaseDetail }) {
  const d = c.decision;
  if (!d)
    return (
      <div className="callout">
        <Info size={16} />
        <div>This case is not waiting for review.</div>
      </div>
    );
  const overridden = c.recommended_route && d.final_route !== c.recommended_route;
  return (
    <Card title="Decision" icon={<ShieldCheck size={15} />} tone="ok">
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <RoutePill route={d.final_route} />
        {overridden && <span className="pill needs_info">override</span>}
      </div>
      <dl style={{ margin: "14px 0 0", display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 14px", fontSize: 13 }}>
        <dt className="faint">Reviewer</dt>
        <dd style={{ margin: 0, fontWeight: 600 }}>{d.reviewer}</dd>
        {c.decided_at && (
          <>
            <dt className="faint">Decided</dt>
            <dd style={{ margin: 0 }}>{dateTime(c.decided_at)}</dd>
          </>
        )}
        {c.recommended_route && (
          <>
            <dt className="faint">Copilot</dt>
            <dd style={{ margin: 0 }}>{ROUTE_LABEL[c.recommended_route]}</dd>
          </>
        )}
      </dl>
      {d.override_reason && (
        <div className="callout info" style={{ marginTop: 14, fontSize: 13 }}>
          <Info size={15} />
          <div>{d.override_reason}</div>
        </div>
      )}
      <Link to={`/cases/${c.case_id}/audit`} className="btn btn-block" style={{ marginTop: 16, height: 38 }}>
        <ScrollText size={15} /> View audit trail
      </Link>
    </Card>
  );
}

function Narrative({ c }: { c: CaseDetail }) {
  return (
    <Card title="Case narrative" icon={<FileText size={15} />} tone="ok" right={<span className="faint">drafted from the analyst's decision</span>}>
      <div className="narrative">{c.narrative || <span className="faint">No narrative stored.</span>}</div>
      {c.narrative_errors.length > 0 && (
        <div className="callout info" style={{ marginTop: 14, fontSize: 13 }}>
          <TriangleAlert size={15} />
          <div>Narrative checks still failing: {c.narrative_errors.join("; ")}</div>
        </div>
      )}
    </Card>
  );
}

function CaseSkeleton() {
  return (
    <div className="case-grid">
      <div className="stack">
        <div className="card card-pad" style={{ display: "flex", gap: 18 }}>
          <Skeleton h={56} w={56} r={16} />
          <div style={{ flex: 1, display: "grid", gap: 10 }}>
            <Skeleton h={24} w="40%" />
            <Skeleton h={14} w="60%" />
            <Skeleton h={22} w="50%" />
          </div>
        </div>
        {[180, 260, 140].map((h, i) => (
          <div key={i} className="card card-pad">
            <Skeleton h={h} />
          </div>
        ))}
      </div>
      <div className="rail">
        <div className="card card-pad">
          <Skeleton h={160} />
        </div>
        <div className="card card-pad">
          <Skeleton h={260} />
        </div>
      </div>
    </div>
  );
}
