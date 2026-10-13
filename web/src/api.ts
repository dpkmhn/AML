// Types mirror app/schemas.py and app/graph/pack.py; the client talks only to the FastAPI service.

export type Route = "close" | "escalate" | "needs_info";
export type AlertStatus = "open" | "in_review" | "closed";
export type CaseStatus = "awaiting_review" | "decided" | "incomplete";
export type Typology =
  | "structuring"
  | "pass_through"
  | "funnel"
  | "profile_mismatch"
  | "dormant_reactivation"
  | "high_risk_geo";

export interface AlertListItem {
  alert_id: string;
  customer_id: string;
  customer_name: string;
  rule_id: string;
  window_start: string;
  window_end: string;
  created_at: string;
  status: AlertStatus;
  case_id: string | null;
  recommended_route: Route | null;
  final_route: Route | null;
}

export interface Txn {
  txn_id: string;
  customer_id: string;
  ts: string;
  amount_aed: number;
  direction: "in" | "out";
  channel: "cash" | "transfer" | "card";
  counterparty_id: string | null;
  counterparty_name: string | null;
  counterparty_country: string | null;
  reference: string | null; // customer-written: untrusted, rendered as text only
}

export interface Finding {
  typology: Typology;
  score: number;
  evidence_txn_ids: string[];
  rule_explanation: string;
}

export interface BenignExplanation {
  typology: Typology;
  explanation: string;
  kyc_quote: string | null;
  evidence_txn_ids: string[];
  cited_chunk_ids: string[];
}

export interface Assessment {
  activity_summary: string;
  benign_explanations: BenignExplanation[];
  concerns: string[];
  cited_chunk_ids: string[];
  missing_information: { item: string; changes_decision: boolean }[];
  confidence: number;
}

export interface RouteDecision {
  route: Route;
  rule_ids: string[];
  reasons: string[];
  fired_typologies: Typology[];
  explained_typologies: Typology[];
}

export interface Pack {
  case_id: string;
  alert: {
    alert_id: string;
    customer_id: string;
    rule_id: string;
    window_start: string;
    window_end: string;
    created_at: string;
    status: AlertStatus;
  };
  customer: {
    customer_id: string;
    full_name: string;
    segment: string;
    occupation: string;
    declared_monthly_income_aed: number;
    expected_activity: string;
    risk_rating: "low" | "medium" | "high";
    is_pep: boolean;
    account_opened: string;
    kyc_notes: string;
  };
  summary: {
    review_start: string;
    review_end: string;
    baseline_start: string;
    txn_count: number;
    inflow_aed: number;
    outflow_aed: number;
    cash_share: number;
    max_single_txn_aed: number;
    baseline_monthly_inflow_aed: number;
  };
  findings: Finding[];
  assessment: Assessment | null;
  assessment_errors: string[];
  flagged_references: { txn_id: string; reference: string | null; note: string }[];
  guidance: { chunk_id: string; typology: string; section: string; cited: boolean }[];
  route: RouteDecision;
}

export interface Decision {
  reviewer: string;
  final_route: Route;
  override_reason: string | null;
  edits?: string | null;
}

export interface CaseDetail {
  case_id: string;
  alert_id: string;
  status: CaseStatus;
  recommended_route: Route | null;
  pack: Pack | null;
  evidence_txns: Txn[];
  guidance_content: Record<string, string>;
  decision: Decision | null;
  narrative: string | null;
  narrative_errors: string[];
  decided_at: string | null;
}

export interface AuditRow {
  id: number;
  step: string;
  model: string | null;
  prompt_version: string | null;
  output: unknown;
  tokens_in: number | null;
  tokens_out: number | null;
  latency_ms: number | null;
  created_at: string;
}

export interface Health {
  status: string;
  model_small: string;
  model_strong: string;
  prompt_version: number;
  openai_key_set: boolean;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  if (!r.ok) {
    let detail: unknown = r.statusText;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    const msg = Array.isArray(detail)
      ? detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join("; ")
      : String(detail);
    throw new ApiError(r.status, msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/health"),
  alerts: () => request<AlertListItem[]>("/alerts"),
  case: (id: string) => request<CaseDetail>(`/cases/${encodeURIComponent(id)}`),
  audit: (id: string) => request<AuditRow[]>(`/cases/${encodeURIComponent(id)}/audit`),
  openCase: (alert_id: string) =>
    request<CaseDetail>("/cases", { method: "POST", body: JSON.stringify({ alert_id }) }),
  review: (id: string, d: Decision) =>
    request<unknown>(`/cases/${encodeURIComponent(id)}/review`, {
      method: "POST",
      body: JSON.stringify(d),
    }),
};
