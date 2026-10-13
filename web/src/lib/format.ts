import type { Route, Typology } from "../api";

export const ROUTE_LABEL: Record<Route, string> = {
  escalate: "Escalate",
  needs_info: "Needs more info",
  close: "Close",
};

export const TYPOLOGY_LABEL: Record<Typology, string> = {
  structuring: "Structuring",
  pass_through: "Pass-through",
  funnel: "Funnel account",
  profile_mismatch: "Profile mismatch",
  dormant_reactivation: "Dormant reactivation",
  high_risk_geo: "High-risk geography",
};

export const RULE_LABEL: Record<string, string> = {
  "TM-PM-01": "Profile mismatch",
  "TM-GEO-01": "High-risk geography",
  "TM-FUN-01": "Funnel",
  "TM-PT-01": "Pass-through",
  "TM-STR-01": "Structuring",
  "TM-DOR-01": "Dormant reactivation",
};

const aed0 = new Intl.NumberFormat("en-AE", { maximumFractionDigits: 0 });
const aed2 = new Intl.NumberFormat("en-AE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });

export const aed = (n: number, precise = false) => `AED ${(precise ? aed2 : aed0).format(n)}`;
export const compactAed = (n: number) => `AED ${compact.format(n)}`;

const asDate = (s: string) => new Date(s.length === 10 ? `${s}T00:00:00Z` : s);

export const date = (s: string) =>
  asDate(s).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });

export const shortDate = (s: string) =>
  asDate(s).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

export const dateTime = (s: string) =>
  asDate(s).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }) + " UTC";

export const pct = (n: number) => `${Math.round(n * 100)}%`;

export const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");

export const stepLabel = (step: string) => step.replace(/_/g, " ");

export const txnTime = (s: string) =>
  asDate(s).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  });
