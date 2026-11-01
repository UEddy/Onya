export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`);
  } catch {
    throw new ApiError(0, "the data service is unreachable");
  }
  if (!res.ok) {
    throw new ApiError(res.status, `request failed (${res.status})`);
  }
  return (await res.json()) as T;
}

/* ---------- formatting: never show raw floats ---------- */

const MISSING = "Not disclosed";

export function formatRatio(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return MISSING;
  return `${v.toFixed(2)}x`;
}

export function formatSignedRatio(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return MISSING;
  const sign = v < 0 ? "\u2212" : v > 0 ? "+" : "";
  return `${sign}${Math.abs(v).toFixed(2)}x`;
}

export function formatMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return MISSING;
  const rounded = Math.round(v);
  const sign = rounded < 0 ? "\u2212" : "";
  return `${sign}$${Math.abs(rounded).toLocaleString("en-US")}`;
}

/* Short prose form: $50M, $44M, $99.5M, $267.2M. Exact whole millions
   drop the decimal; anything else rounds to one decimal. */
export function formatShortMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return MISSING;
  const sign = v < 0 ? "\u2212" : "";
  const abs = Math.abs(v);
  if (abs >= 1_000_000) {
    const millions = abs / 1_000_000;
    const text =
      abs % 1_000_000 === 0
        ? String(Math.round(millions))
        : millions.toFixed(1);
    return `${sign}$${text}M`;
  }
  return formatMoney(v);
}

export function formatMillions(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return MISSING;
  const sign = v < 0 ? "\u2212" : "";
  return `${sign}$${(Math.abs(v) / 1_000_000).toFixed(1)}M`;
}

export function formatDateLong(periodEnd: string): string {
  const months = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(periodEnd);
  if (!m) return periodEnd;
  return `${months[Number(m[2]) - 1] || m[2]} ${Number(m[3])}, ${m[1]}`;
}

export function formatInt(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return MISSING;
  return Math.round(v).toLocaleString("en-US");
}

export function formatClock(iso: string | null | undefined): string {
  if (!iso) return MISSING;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return MISSING;
  return d.toLocaleTimeString("en-US", { hour12: false });
}

export function formatPeriod(periodEnd: string): string {
  const months = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(periodEnd);
  if (!m) return periodEnd;
  const month = months[Number(m[2]) - 1] || m[2];
  return `${month} ${m[1]}`;
}

/* ---------- shared types ---------- */

export interface CompanyRow {
  ticker: string;
  name: string;
  period_end: string | null;
  as_of: string | null;
  covenant: string | null;
  ratio: number | null;
  threshold: number | null;
  headroom: number | null;
  status: "pass" | "fail" | "unknown";
  scenarios?: Scenario[] | null;
  ratio_with_savings?: number | null;
  ratio_without_savings?: number | null;
}

export interface Verdict {
  ratio: number | null;
  ratio_2dp: number | null;
  threshold: number | null;
  headroom: number | null;
  headroom_2dp: number | null;
  pass: boolean | null;
  note?: string | null;
  numerator_value?: number | null;
  denominator_value?: number | null;
}

export interface Scenario {
  savings: number;
  ebitda: number;
  ebitdar: number;
  net_leverage: Verdict;
  interest_coverage: Verdict;
  note?: string | null;
}

export interface PeriodSummary {
  period_end: string;
  net_leverage: Verdict;
  interest_coverage: Verdict;
  scenarios: Scenario[] | null;
}

export interface ComponentRow {
  name: string;
  value: number | null;
  source: string;
  clause: string | null;
  note: string | null;
}

export interface PeriodDetail {
  period_end: string;
  components: ComponentRow[];
  data_quality_warnings: {
    concept: string;
    period_end: string;
    direct: number;
    derived: number;
  }[];
  numerator: number;
  ebitda: number;
  ebitdar: number;
  net_leverage: Verdict;
  interest_coverage: Verdict;
  reconciliation?: {
    status: string;
    note: string;
    company_ebitda: number | null;
    onya_ebitda: number | null;
    difference: number | null;
    net_leverage?: { company_reported: Verdict; onya_strict: Verdict };
    interest_coverage?: { company_reported: Verdict; onya_strict: Verdict };
  } | null;
  sensitivity_without_proforma?: {
    net_leverage: Verdict;
    interest_coverage: Verdict;
    note: string;
  } | null;
  proforma_scenarios?: Scenario[] | null;
  covenant_clause?: {
    name: string | null;
    section: string | null;
    quote: string | null;
    threshold: number | null;
    period_end: string | null;
  } | null;
  cure?: {
    base: Record<string, CureBlock>;
    equity_cure?: {
      found: boolean;
      present?: boolean | null;
      section?: string | null;
      note: string;
    };
    proforma_scenarios?: {
      savings: number;
      net_leverage: CureBlock;
      interest_coverage: CureBlock;
    }[];
  } | null;
  projection?: Projection | null;
  flags?: {
    data_quality_warnings: PeriodDetail["data_quality_warnings"];
    warning_count: number;
    reconciliation: string | PeriodDetail["reconciliation"];
    unverifiable_proforma: boolean;
  } | null;
  scenarios?: Scenario[] | null;
}

export interface CureBlock {
  status: string;
  summary?: string;
  figures?: Record<
    string,
    { value: number; formula?: string; detail?: string; note?: string }
  >;
}

export interface Projection {
  base: string;
  baseline?: { company_source?: string | null } | null;
  next_test: string;
  next_threshold: number | null;
  threshold_note?: string | null;
  projections: {
    onya: Verdict & { ebitda?: number; ebitdar?: number };
    company: Verdict & { ebitda?: number; ebitdar?: number };
  };
  cushion?: { onya: number | null; company: number | null };
  quarters_of_cushion?: { onya: number | null; company: number | null };
  risk?: { onya: string; company: string };
  risk_rule?: string;
  trend?: {
    series: { period_end: string; adjusted_ebitda: number }[];
  };
}

export interface Backtest {
  disclosed: {
    rows: {
      ticker: string;
      covenant: string;
      direction?: string | null;
      waived_threshold?: number | null;
      actual_ext: number | null;
      actual_key: number | null;
      actual_match: boolean;
      threshold_ext: number | null;
      threshold_key: number | null;
      threshold_match: boolean;
      matched: boolean;
      verified: boolean;
      matched_and_verified: boolean;
    }[];
    totals: {
      covenants: number;
      actual_matched: number;
      threshold_matched: number;
      fully_matched: number;
      matched: number;
      verified: number;
      matched_and_verified: number;
    };
    notes: string[];
  };
  terms: {
    rows: {
      ticker: string;
      name: string;
      direction: string;
      agreement_threshold: number | null;
      disclosed_threshold: number | null;
      match: boolean;
      quote_verified: boolean;
      status: string;
    }[];
    totals: {
      covenants: number;
      companies: number;
      matched: number;
      amended_after_agreement: number;
      no_disclosed_match: number;
      mismatched: number;
      quote_verified: number;
    };
    records: { ticker: string; period_end: string; status: string }[];
    notes: string[];
  };
}

export interface AgentStep {
  step: number | null;
  timestamp: string | null;
  type: string | null;
  tool: string | null;
  arguments: Record<string, unknown>;
  result_summary: string;
  total_tokens: number;
}

export interface AgentRunState {
  run_id: string;
  status: string;
  reason: string | null;
  steps: AgentStep[];
  answer: string | null;
  total_tokens: number;
  tool_calls: number;
  error: string | null;
  figure_fields?: { raw: string; field: string; value: number }[];
}

export interface SampleMemo {
  ticker: string;
  period_end: string;
  as_of: string | null;
  memo: string;
  run_id: string;
  tool_calls: number;
  total_tokens: number;
  timestamp: string;
  figure_fields?: { raw: string; field: string; value: number }[];
  figures_checked?: number | null;
  steps?: AgentStep[];
}

export type SourceEvidence =
  | {
      kind: "contract";
      ref: string;
      clauses: {
        clause_ref: string;
        term: string | null;
        section: string | null;
        label: string | null;
        quote: string | null;
      }[];
      cap?: {
        applies_to_clauses?: string[] | null;
        quote: string | null;
      } | null;
    }
  | {
      kind: "xbrl";
      ref: string;
      concept: string;
      label: string | null;
      value: number | null;
      period_end: string | null;
      facts: {
        val: number | null;
        end: string | null;
        start?: string | null;
        unit: string | null;
        form: string | null;
        filed: string | null;
      }[];
    }
  | {
      kind: "release";
      ref: string;
      matches: {
        period_end: string | null;
        table: string | null;
        line: string | null;
        value_thousands: number | null;
        quote: string | null;
      }[];
    };
