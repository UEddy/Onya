"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { EvidencePanel, sourceKind } from "./evidence";
import {
  HeadroomChart,
  loadHeadroomPoints,
  type HeadroomPoint,
} from "./headroom-chart";
import WhatIfPanel from "./what-if";
import {
  ErrorLine,
  LoadingLine,
  Panel,
  StatusMark,
  StatusPill,
} from "./site";
import { Reveal } from "./fade-up";
import {
  apiGet,
  formatDateLong,
  formatMoney,
  formatPeriod,
  formatRatio,
  formatShortMoney,
  formatSignedRatio,
  type ComponentRow,
  type FilingsSince,
  type PeriodDetail,
  type PeriodSummary,
  type Verdict,
} from "../lib/api";
import { RequestActions, RequestView } from "./request";
import { useWatch } from "../lib/watch";

function savingsLabel(savings: number): string {
  if (savings >= 1_000_000 && savings % 1_000_000 === 0) {
    return `$${savings / 1_000_000}M`;
  }
  return formatMoney(savings);
}

function verdictHeadline(detail: PeriodDetail): string {
  const scenarios = detail.scenarios ?? detail.proforma_scenarios ?? [];
  if (scenarios.length > 0) {
    if (scenarios.every((s) => s.net_leverage.pass === false)) {
      return "Breach under every scenario";
    }
    if (scenarios.some((s) => s.net_leverage.pass === true)) {
      return scenarios.every((s) => s.net_leverage.pass === true)
        ? "Pass"
        : "Passes only with projected savings";
    }
    return "Breach under every scenario";
  }
  const sensitivity = detail.sensitivity_without_proforma;
  if (
    detail.net_leverage.pass === true &&
    sensitivity &&
    sensitivity.net_leverage.pass === false
  ) {
    return "Passes only with projected savings";
  }
  return detail.net_leverage.pass === true ? "Pass" : "Breach";
}

function VerdictFigure({
  verdict,
  caption,
  anchorId,
}: {
  verdict: Verdict;
  caption: string;
  anchorId?: string;
}) {
  return (
    <div id={anchorId} className="card-inset p-5">
      <p className="text-[44px] font-semibold leading-none tracking-tight">
        {formatRatio(verdict.ratio_2dp ?? verdict.ratio)}
      </p>
      <p className="mt-2 text-[15px]">{caption}</p>
      <p className="mt-1 text-[13px] text-ink-muted">
        Limit {formatRatio(verdict.threshold)}. Headroom{" "}
        {formatSignedRatio(verdict.headroom_2dp ?? verdict.headroom)}
      </p>
    </div>
  );
}

export function VerdictBlock({ detail }: { detail: PeriodDetail }) {
  const headline = verdictHeadline(detail);
  const scenarios = detail.scenarios ?? detail.proforma_scenarios ?? [];
  const sensitivity = detail.sensitivity_without_proforma;
  const proforma =
    detail.components.find((c) => c.name === "Pro forma cost savings")?.value ?? 0;
  const lev = detail.net_leverage;
  const sortedScenarios = [...scenarios].sort((a, b) => b.savings - a.savings);
  const headlineTone = headline === "Pass" ? "pass" : headline.startsWith("Passes") ? "watch" : "breach";
  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-[22px] font-semibold tracking-tight">{headline}</h2>
        <StatusPill
          tone={headlineTone}
          word={headlineTone === "pass" ? "Pass" : headlineTone === "watch" ? "Watch" : "Breach"}
        />
      </div>
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        {sortedScenarios.length > 0 ? (
          sortedScenarios.map((s) => (
            <VerdictFigure
              key={s.savings}
              anchorId={s.savings > 0 ? "fig-net_leverage" : "fig-net_leverage_without"}
              verdict={s.net_leverage}
              caption={
                s.savings > 0
                  ? `with ${savingsLabel(s.savings)} of projected savings`
                  : "without"
              }
            />
          ))
        ) : sensitivity ? (
          <>
            <VerdictFigure
              anchorId="fig-net_leverage"
              verdict={lev}
              caption={`with ${savingsLabel(proforma)} of projected savings`}
            />
            <VerdictFigure anchorId="fig-net_leverage_without" verdict={sensitivity.net_leverage} caption="without" />
          </>
        ) : (
          <VerdictFigure anchorId="fig-net_leverage" verdict={lev} caption="Net leverage" />
        )}
      </div>
      <p className="mt-4 text-[15px] text-ink-muted">
        Interest coverage {formatRatio(detail.interest_coverage.ratio_2dp ?? detail.interest_coverage.ratio)}{" "}
        against at least {formatRatio(detail.interest_coverage.threshold)}. Headroom{" "}
        {formatSignedRatio(detail.interest_coverage.headroom_2dp ?? detail.interest_coverage.headroom)}.
      </p>
    </div>
  );
}

const DEBT_NAMES = new Set([
  "Borrowings under credit facility",
  "Outstanding letters of credit",
  "Finance lease obligations",
  "Operating lease liabilities",
  "Unrestricted US cash in excess of $40,000,000",
]);

function clauseLabel(clause: string | null): string {
  if (clause === "definition: Net Leverage Ratio") return "Leverage definition";
  if (clause === "definition: Consolidated EBITDA") return "EBITDA definition";
  if (clause === "definition: Consolidated Rent Expense") return "Rent definition";
  return clause ?? "";
}

function ComponentTableRow({
  component,
  active,
  onSelect,
}: {
  component: ComponentRow;
  active: boolean;
  onSelect: (component: ComponentRow | null) => void;
}) {
  const anchorId =
    component.name === "Interest expense"
      ? "fig-interest_expense"
      : component.name.startsWith("Disallowed")
        ? "fig-disallowed"
        : undefined;
  return (
    <div id={anchorId} className={`grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 border-b border-hairline px-2 py-2.5 transition-colors lg:grid-cols-[minmax(0,1fr)_130px_100px_150px] ${active ? "rounded-lg bg-inset" : ""}`}>
      <span className="text-[15px]">{component.name}</span>
      <span className="text-right">
        <button
          type="button"
          onClick={() => onSelect(active ? null : component)}
          aria-expanded={active}
          title="Show the evidence for this figure"
          className="text-[15px] font-medium underline decoration-rule underline-offset-4 hover:decoration-ink"
        >
          {formatMoney(component.value)}
        </button>
      </span>
      <span className="col-span-2 mt-1 flex gap-x-4 text-[13px] lg:col-span-1 lg:mt-0">
        <button
          type="button"
          onClick={() => onSelect(active ? null : component)}
          aria-expanded={active}
          className="text-ink-muted underline decoration-rule underline-offset-4 hover:text-ink"
        >
          {sourceKind(component.source)}
        </button>
        <span className="whitespace-nowrap text-ink-muted lg:hidden">{clauseLabel(component.clause)}</span>
      </span>
      <span className="hidden whitespace-nowrap text-[13px] text-ink-muted lg:block">
        {clauseLabel(component.clause)}
      </span>
    </div>
  );
}

function SubtotalRow({ label, value, anchorId }: { label: string; value: number; anchorId?: string }) {
  return (
    <div id={anchorId} className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 border-b border-hairline border-t-2 border-t-ink px-2 py-2.5 font-semibold lg:grid-cols-[minmax(0,1fr)_130px_100px_150px]">
      <span className="text-[15px]">{label}</span>
      <span className="text-right text-[15px]">{formatMoney(value)}</span>
      <span />
      <span />
    </div>
  );
}

function GroupHeading({ children }: { children: string }) {
  return (
    <h3 className="eyebrow border-b border-hairline px-2 pb-2 pt-6 first:pt-0">
      {children}
    </h3>
  );
}

export interface SubtotalBuild {
  label: string;
  rows: ComponentRow[];
  total: number;
}

function EvidenceMargin({
  detail,
  selected,
  build,
}: {
  detail: PeriodDetail;
  selected: ComponentRow | null;
  build?: SubtotalBuild | null;
}) {
  if (build) {
    return (
      <div>
        <p className="text-[13px] font-medium">{build.label}</p>
        <ul className="mt-2 space-y-2">
          {build.rows.map((row) => (
            <li key={row.name} className="text-[13px]">
              <span className="font-medium">{formatMoney(row.value)}</span>{" "}
              <span className="text-ink-muted">
                {row.name} ({sourceKind(row.source)})
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-3 border-t border-rule pt-2 text-[15px] font-semibold">
          {formatMoney(build.total)}
        </p>
      </div>
    );
  }
  if (selected && selected.name.startsWith("Disallowed")) {
    const cash =
      detail.components.find((c) => c.name === "Cash restructuring expenses")?.value ?? 0;
    const other =
      detail.components.find((c) => c.name === "Other non-recurring items")?.value ?? 0;
    const disallowed = Math.abs(selected.value ?? 0);
    const cap = cash + other - disallowed;
    return (
      <div>
        <EvidencePanel
          key={`${detail.period_end}:${selected.source}`}
          source={selected.source}
          periodEnd={detail.period_end}
        />
        <p className="mt-4 text-[13px]">
          Cash restructuring {formatMoney(cash)} plus other non-recurring{" "}
          {formatMoney(other)} is {formatMoney(cash + other)}, against a cap
          of {formatMoney(cap)}. The {formatMoney(disallowed)} above the cap
          is disallowed.
        </p>
      </div>
    );
  }
  if (selected) {
    return (
      <EvidencePanel
        key={`${detail.period_end}:${selected.source}`}
        source={selected.source}
        periodEnd={detail.period_end}
      />
    );
  }
  const clause = detail.covenant_clause;
  return (
    <div>
      <p className="text-[13px] font-medium">
        Net Leverage covenant
        {clause?.section ? `, section ${clause.section}` : ""}
      </p>
      {clause?.quote && (
        <blockquote className="quote mt-2 border-l-2 border-rule pl-3 text-[15px]">
          {clause.quote}
        </blockquote>
      )}
      <p className="mt-3 text-[13px] text-ink-muted">
        Limit for this period: {formatRatio(clause?.threshold ?? detail.net_leverage.threshold)}
      </p>
      <p className="mt-1 text-[13px] text-ink-muted">
        Select any figure or source to read its evidence here.
      </p>
    </div>
  );
}

export function ComponentsSection({ detail }: { detail: PeriodDetail }) {
  const [selected, setSelected] = useState<ComponentRow | null>(null);
  const [build, setBuild] = useState<SubtotalBuild | null>(null);
  useEffect(() => {
    const hash = window.location.hash;
    if (!hash.startsWith("#fig-")) return;
    const field = decodeURIComponent(hash.slice("#fig-".length));
    const byName = (name: string) =>
      detail.components.find((c) => c.name === name) ?? null;
    const debtRows = detail.components.filter((c) => DEBT_NAMES.has(c.name));
    const buildRows = detail.components.filter(
      (c) =>
        !DEBT_NAMES.has(c.name) &&
        c.name !== "Consolidated rent expense" &&
        c.name !== "Covenant EBITDA reconciliation",
    );
    const rentRows = detail.components.filter(
      (c) => c.name === "Consolidated rent expense",
    );
    const subtotal =
      field === "total_debt"
        ? { label: "Total debt including operating leases", rows: debtRows, total: detail.numerator }
        : field === "ebitda"
          ? { label: "Consolidated EBITDA", rows: buildRows, total: detail.ebitda }
          : field === "ebitdar"
            ? { label: "Consolidated EBITDAR", rows: [...buildRows, ...rentRows], total: detail.ebitdar }
            : null;
    if (subtotal) {
      const timer = window.setTimeout(() => setBuild(subtotal), 0);
      return () => window.clearTimeout(timer);
    }
    const target =
      field === "interest_expense"
        ? byName("Interest expense")
        : field === "disallowed"
          ? (detail.components.find((c) => c.name.startsWith("Disallowed")) ??
            null)
          : null;
    if (target) {
      const timer = window.setTimeout(() => setSelected(target), 0);
      return () => window.clearTimeout(timer);
    }
  }, [detail]);
  const debt = detail.components.filter((c) => DEBT_NAMES.has(c.name));
  const rent = detail.components.filter(
    (c) => c.name === "Consolidated rent expense",
  );
  const reconciliation = detail.components.filter(
    (c) => c.name === "Covenant EBITDA reconciliation",
  );
  const ebitdaBuild = detail.components.filter(
    (c) =>
      !DEBT_NAMES.has(c.name) &&
      c.name !== "Consolidated rent expense" &&
      c.name !== "Covenant EBITDA reconciliation",
  );
  const renderRow = (component: ComponentRow) => (
    <ComponentTableRow
      key={component.name}
      component={component}
      active={selected?.source === component.source && selected?.name === component.name}
      onSelect={(c) => {
        setBuild(null);
        setSelected(c);
      }}
    />
  );
  return (
    <div className="grid gap-x-8 lg:grid-cols-[minmax(0,1fr)_300px]">
      <div>
        <div className="hidden grid-cols-[minmax(0,1fr)_130px_100px_150px] gap-x-4 border-b border-hairline px-2 py-2 text-[13px] text-ink-muted lg:grid">
          <span>Component</span>
          <span className="text-right">Value</span>
          <span>Source</span>
          <span>Clause</span>
        </div>
        <GroupHeading>Debt</GroupHeading>
        {debt.map(renderRow)}
        <SubtotalRow anchorId="fig-total_debt" label="Total debt including operating leases" value={detail.numerator} />
        <GroupHeading>EBITDA build-up</GroupHeading>
        {ebitdaBuild.map(renderRow)}
        <SubtotalRow anchorId="fig-ebitda" label="Consolidated EBITDA" value={detail.ebitda} />
        {rent.map(renderRow)}
        <SubtotalRow anchorId="fig-ebitdar" label="Consolidated EBITDAR" value={detail.ebitdar} />
        {reconciliation.map(renderRow)}
      </div>
      <aside className="mt-6 self-start lg:sticky lg:top-24 lg:mt-0">
        <div
          key={`${selected?.name ?? ""}:${build?.label ?? ""}`}
          className="card-float enter pop-out p-5"
          style={{ ["--pop-x" as string]: "18px" }}
        >
          <p className="eyebrow border-b border-hairline pb-2">
            Evidence
          </p>
          <div className="pt-3">
            <EvidenceMargin detail={detail} selected={selected} build={build} />
          </div>
        </div>
      </aside>
    </div>
  );
}

function FlagsPanel({ detail }: { detail: PeriodDetail }) {
  const flags = detail.flags;
  const reconciliation = flags?.reconciliation ?? detail.reconciliation ?? null;
  const warnings = flags?.data_quality_warnings ?? detail.data_quality_warnings ?? [];
  const scenarios = detail.scenarios ?? detail.proforma_scenarios ?? [];
  const unverifiable = flags?.unverifiable_proforma ?? scenarios.length > 0;
  const sensitivity = detail.sensitivity_without_proforma ?? null;

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="card-inset p-5">
        <h3 className="text-[15px] font-medium">Reconciliation</h3>
        {typeof reconciliation === "string" ? (
          <p className="mt-1 max-w-[75ch] text-[15px] text-ink-muted">
            {reconciliation === "not available (no company leverage table disclosed)"
              ? "No comparison is possible: the company disclosed no leverage table this quarter."
              : reconciliation}
          </p>
        ) : reconciliation ? (
          <div className="mt-1">
            <StatusMark
              tone={reconciliation.status === "reconciled" ? "pass" : "watch"}
              word={reconciliation.status === "reconciled" ? "Reconciled" : "Flagged"}
            />
            <p className="mt-1 max-w-[75ch] text-[15px] text-ink-muted">
              {reconciliation.note}
            </p>
            {reconciliation.status !== "reconciled" && (
              <p className="mt-1 text-[15px]">
                Company {formatMoney(reconciliation.company_ebitda)} against
                Onya {formatMoney(reconciliation.onya_ebitda)}, a difference
                of {formatMoney(reconciliation.difference)}.
              </p>
            )}
          </div>
        ) : (
          <p className="mt-1 text-[15px] text-ink-muted">
            No reconciliation for this period.
          </p>
        )}
      </div>

      <div className="card-inset p-5">
        <h3 className="text-[15px] font-medium">
          Data quality warnings ({warnings.length})
        </h3>
        {warnings.length === 0 ? (
          <p className="mt-1 text-[15px] text-ink-muted">
            No warnings this period.
          </p>
        ) : (
          <ul className="mt-2 space-y-2">
            {warnings.map((warning, i) => (
              <li key={`${warning.concept}-${warning.period_end}-${i}`} className="max-w-[75ch] text-[15px]">
                Sleep Number&apos;s XBRL reported {formatMoney(warning.direct)}{" "}
                for the quarter ended {formatDateLong(warning.period_end)}; its
                audited annual figures imply {formatMoney(warning.derived)}.
                Onya used the audited figure.
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="card-inset p-5">
        <h3 className="text-[15px] font-medium">Unverifiable add-backs</h3>
        {!unverifiable && !sensitivity ? (
          <p className="mt-1 text-[15px] text-ink-muted">
            Every add-back this period traces to a filed figure.
          </p>
        ) : (
          <div className="mt-1 space-y-2">
            {sensitivity && (
              <p className="max-w-[75ch] text-[15px]">{sensitivity.note}: net
                leverage would be {formatRatio(sensitivity.net_leverage.ratio_2dp)} against{" "}
                {formatRatio(sensitivity.net_leverage.threshold)}.</p>
            )}
            {scenarios.map((scenario) => (
              <p key={scenario.savings} className="max-w-[75ch] text-[15px]">
                {formatMoney(scenario.savings)} of projected savings would
                leave net leverage at {formatRatio(scenario.net_leverage.ratio_2dp)} against{" "}
                {formatRatio(scenario.net_leverage.threshold)}. The savings
                require administrative agent approval, so Onya treats them as unverified.
              </p>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function cureText(text: string | undefined): string {
  return (text ?? "No summary.")
    .replaceAll("Net Leverage", "net leverage")
    .replaceAll("Interest Coverage", "interest coverage")
    .replace(/(\d+\.\d)x(?!\d)/g, (_m, g: string) => `${g}0x`);
}

function figureLabel(name: string): string {
  const labels: Record<string, string> = {
    debt_reduction_needed: "Debt reduction needed",
    ebitda_increase_needed: "EBITDA increase needed",
    interest_reduction_needed: "Interest reduction needed",
  };
  return labels[name] ?? name.replace(/_/g, " ");
}

export function CurePanel({ detail }: { detail: PeriodDetail }) {
  const cure = detail.cure;
  if (!cure) {
    return (
      <p className="text-[15px] text-ink-muted">
        No cure analysis for this period.
      </p>
    );
  }
  const blocks = [
    ["Net leverage", cure.base.net_leverage],
    ["Interest coverage", cure.base.interest_coverage],
  ] as const;
  const equity = cure.equity_cure;
  const noEquityCure =
    equity !== undefined &&
    (equity.present === false ||
      (equity.present === null && equity.found === false) ||
      (equity.present === undefined && equity.found === false));
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {blocks.map(
        ([title, block]) =>
          block && (
            <div key={title} className="card-inset p-5">
              <h3 className="text-[15px] font-medium">{title}</h3>
              <p className="mt-1 max-w-[75ch] text-[15px]">
                <StatusMark
                  tone={block.status === "pass" ? "pass" : "breach"}
                  word={block.status === "pass" ? "Pass" : "Breach"}
                />{" "}
                {cureText(block.summary)}
              </p>
              {block.figures && (
                <ul className="mt-2 space-y-1">
                  {Object.entries(block.figures).map(([name, figure]) => (
                    <li
                      key={name}
                      id={
                        name === "debt_reduction_needed"
                          ? "fig-cure.debt_reduction"
                          : name === "ebitda_increase_needed"
                            ? title === "Net leverage"
                              ? "fig-cure.ebitda_increase"
                              : "fig-cure.interest_ebitda_increase"
                            : undefined
                      }
                      className="max-w-[75ch] text-[13px] text-ink-muted">
                      {`${figureLabel(name)}: ${formatMoney(figure.value)}`}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ),
      )}
      {equity && noEquityCure && (
        <p className="max-w-[75ch] text-[15px] sm:col-span-2">
          No equity cure provision was found in the reviewed agreement.
        </p>
      )}
      {equity && !noEquityCure && (
        <p className="max-w-[75ch] text-[15px] text-ink-muted sm:col-span-2">
          Equity cure provision found in the reviewed agreement
          {equity.section ? `, section ${equity.section}` : ""}.
        </p>
      )}
      {(cure.proforma_scenarios ?? []).map((scenario) => (
        <div key={scenario.savings} className="card-inset p-5 sm:col-span-2">
          <h3 className="text-[15px] font-medium">
            With {formatShortMoney(scenario.savings)} of projected savings
          </h3>
          <p className="mt-1 max-w-[75ch] text-[15px]">
            {cureText(scenario.net_leverage.summary)}
          </p>
          <p className="mt-1 max-w-[75ch] text-[15px]">
            {cureText(scenario.interest_coverage.summary)}
          </p>
        </div>
      ))}
    </div>
  );
}

export function ProjectionPanel({ detail }: { detail: PeriodDetail }) {
  const projection = detail.projection;
  if (!projection) {
    return (
      <p className="text-[15px] text-ink-muted">
        No projection from this period.
      </p>
    );
  }
  const riskWord = (risk: string) =>
    risk === "HIGH" ? "High" : risk === "MEDIUM" ? "Medium" : "Low";
  const riskTone = (risk: string): "breach" | "watch" | "pass" =>
    risk === "HIGH" ? "breach" : risk === "MEDIUM" ? "watch" : "pass";
  const series = projection.trend?.series ?? [];
  const first = series[0];
  const last = series[series.length - 1];
  const companySource = projection.baseline?.company_source ?? "";
  const hasCompanyView =
    !companySource.startsWith("fallback") &&
    (projection.projections.company.ebitda !== projection.projections.onya.ebitda ||
      projection.projections.company.ratio_2dp !== projection.projections.onya.ratio_2dp);
  const sides = (hasCompanyView ? ["onya", "company"] : ["onya"]) as (
    | "onya"
    | "company"
  )[];
  return (
    <div className="space-y-4">
      <p className="max-w-[75ch] text-[15px]">
        Next test {formatPeriod(projection.next_test)} with a limit of{" "}
        {formatRatio(projection.next_threshold)}. If nothing changes, Onya
        projects {formatRatio(projection.projections.onya.ratio_2dp)}.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        {sides.map((side) => {
          const cushion = projection.cushion?.[side] ?? null;
          return (
            <div key={side} className="card-inset p-5">
              <h3 className="text-[15px] font-medium">
                {side === "onya" ? "Onya view" : "Company view"}
              </h3>
              <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[15px]">
                <span className="text-[30px] font-semibold leading-none tracking-tight">
                  {formatRatio(projection.projections[side].ratio_2dp)}
                </span>
                <StatusMark
                  tone={projection.projections[side].pass ? "pass" : "breach"}
                  word={projection.projections[side].pass ? "Pass" : "Projected breach"}
                />
              </p>
              <p className="mt-1 text-[13px] text-ink-muted">
                {cushion !== null && cushion < 0
                  ? `Needs ${formatShortMoney(Math.abs(cushion))} more EBITDAR to pass at the baseline projection.`
                  : `Cushion ${formatMoney(cushion)}`}
              </p>
              <p className="mt-1 text-[13px] text-ink-muted">
                Risk{" "}
                <StatusMark
                  tone={riskTone(projection.risk?.[side] ?? "LOW")}
                  word={riskWord(projection.risk?.[side] ?? "LOW")}
                />
              </p>
            </div>
          );
        })}
      </div>
      {first && last && series.length > 1 && (
        <p className="max-w-[75ch] text-[15px] text-ink-muted">
          Adjusted EBITDA fell from {formatShortMoney(first.adjusted_ebitda)} in{" "}
          {formatPeriod(first.period_end)} to {formatShortMoney(last.adjusted_ebitda)}{" "}
          in {formatPeriod(last.period_end)}.
        </p>
      )}
      {projection.risk_rule && (
        <p className="max-w-[75ch] text-[13px] text-ink-muted">
          High risk means less than two quarters of decline would cause a
          breach.
        </p>
      )}
    </div>
  );
}

function FiledSinceList({ ticker, date }: { ticker: string; date: string }) {
  const [data, setData] = useState<FilingsSince | null>(null);
  useEffect(() => {
    let cancelled = false;
    apiGet<FilingsSince>(
      `/company/${ticker}/filings-since?date=${date}`,
    ).then(
      (res) => {
        if (!cancelled) setData(res);
      },
      () => {
        if (!cancelled) setData(null);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [ticker, date]);
  if (data === null) {
    return <LoadingLine text="Checking for newer filings." />;
  }
  if (!data.cached) {
    return (
      <p className="max-w-[75ch] text-[15px] text-ink-muted">
        {data.note ?? "The filings cache is missing for this company."}
      </p>
    );
  }
  if (data.filings.length === 0) {
    return (
      <p className="max-w-[75ch] text-[15px] text-ink-muted">
        No 10-K, 10-Q or 8-K filings since {formatDateLong(date)}.
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {data.filings.map((row) => (
        <li key={row.accessionNumber} className="text-[15px]">
          <a
            href={row.sec_url}
            target="_blank"
            rel="noreferrer"
            className="text-link underline decoration-hairline underline-offset-4 hover:text-ink"
          >
            {row.form}, filed {formatDateLong(row.filingDate)}
          </a>
        </li>
      ))}
    </ul>
  );
}

function CaseRequestButton({
  ticker,
  periodEnd,
}: {
  ticker: string;
  periodEnd: string;
}) {
  const [request, setRequest] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const start = () => {
    setRequest(null);
    setRunning(true);
    setFailed(false);
    setAttempt((n) => n + 1);
  };

  useEffect(() => {
    if (attempt === 0) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/request", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ company: ticker, period_end: periodEnd }),
          cache: "no-store",
        });
        if (!res.ok || !res.body) {
          if (!cancelled) {
            setRunning(false);
            setFailed(true);
          }
          return;
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done || cancelled) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.trim()) continue;
            try {
              const event = JSON.parse(line) as {
                type?: string;
                info_request?: string;
              };
              if (event.type === "run_result" && event.info_request) {
                setRequest(event.info_request);
              } else if (event.type === "error") {
                setFailed(true);
              }
            } catch {
              /* Partial line waits for the next chunk. */
            }
          }
        }
        if (!cancelled) setRunning(false);
      } catch {
        if (!cancelled) {
          setRunning(false);
          setFailed(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [attempt, ticker, periodEnd]);

  return (
    <div className="mt-5">
      {!request && !running && !failed && (
        <button
          type="button"
          onClick={start}
          className="btn btn-secondary btn-sm"
        >
          Draft information request
        </button>
      )}
      {running && !request && (
        <LoadingLine text="Drafting the information request." />
      )}
      {failed && !request && (
        <ErrorLine title="The request could not be drafted." onRetry={start}>
          The data service may be waking up. Then try again.
        </ErrorLine>
      )}
      {request && (
        <>
          <p className="text-[13px] text-ink-muted">
            Draft. Review before sending. Nothing has been sent anywhere.
          </p>
          <div className="mt-3">
            <RequestView
              request={request}
              ticker={ticker}
              periodEnd={periodEnd}
            />
          </div>
          <RequestActions
            request={request}
            ticker={ticker}
            periodEnd={periodEnd}
          />
        </>
      )}
    </div>
  );
}

export default function CaseView({ ticker }: { ticker: string }) {
  const { watched, toggle } = useWatch();
  const watching = watched.includes(ticker);
  const [periods, setPeriods] = useState<PeriodSummary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<PeriodDetail | null>(null);
  const [points, setPoints] = useState<HeadroomPoint[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (ticker !== "SNBR") return;
    let cancelled = false;
    Promise.all([
      apiGet<{ ticker: string; periods: PeriodSummary[] }>(
        "/company/SNBR/periods",
      ),
      loadHeadroomPoints().catch(() => null),
    ]).then(
      ([res, chartPoints]) => {
        if (cancelled) return;
        const sorted = [...res.periods].sort((a, b) =>
          a.period_end < b.period_end ? -1 : 1,
        );
        setPeriods(sorted);
        setPoints(chartPoints);
        const requested = new URLSearchParams(window.location.search).get(
          "period",
        );
        setSelected(
          (current) =>
            current ??
            (requested &&
            sorted.some((period) => period.period_end === requested)
              ? requested
              : sorted[sorted.length - 1].period_end),
        );
        setFailed(false);
      },
      () => {
        if (!cancelled) setFailed(true);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [ticker, attempt]);

  useEffect(() => {
    if (ticker !== "SNBR" || !selected) return;
    let cancelled = false;
    apiGet<PeriodDetail>(`/company/SNBR/period/${selected}`).then(
      (data) => {
        if (cancelled) return;
        setDetail(data);
        setFailed(false);
      },
      () => {
        if (!cancelled) setFailed(true);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [ticker, selected, attempt]);

  const visibleDetail =
    detail && detail.period_end === selected ? detail : null;

  useEffect(() => {
    if (!visibleDetail) return;
    const hash = window.location.hash;
    if (!hash.startsWith("#fig-")) return;
    const id = decodeURIComponent(hash.slice(1));
    const timer = window.setTimeout(() => {
      const el = document.getElementById(id);
      if (!el) return;
      el.scrollIntoView({ block: "start" });
      el.classList.add("figure-highlight");
      window.setTimeout(() => el.classList.remove("figure-highlight"), 2000);
    }, 80);
    return () => window.clearTimeout(timer);
  }, [visibleDetail]);

  if (ticker !== "SNBR") {
    return (
      <div className="card enter mt-6 p-6 sm:p-8">
        <h1 className="text-[30px] font-semibold tracking-tight">
          Only Sleep Number is covered.
        </h1>
        <p className="mt-2 max-w-[65ch] text-[15px] text-ink-muted">
          Onya has a full case file for Sleep Number so far.
        </p>
        <Link href="/app/company/SNBR" className="btn btn-primary mt-5">
          Open the Sleep Number case
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-5 pb-10 pt-6">
      <div className="enter flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div>
          <p className="eyebrow">SNBR</p>
          <h1 className="mt-2 text-[30px] font-semibold leading-tight tracking-tight sm:text-[36px]">
            Sleep Number
          </h1>
          <p className="mt-1 text-[15px] text-ink-muted">
            SNBR, quarter ended {selected ? formatPeriod(selected) : ""}
          </p>
          <p className="mt-2">
            <button
              type="button"
              aria-pressed={watching}
              aria-label={watching ? "Stop watching SNBR" : "Watch SNBR"}
              onClick={() => toggle(ticker)}
              className="text-[15px] text-link underline decoration-hairline underline-offset-4 hover:text-ink"
            >
              {watching ? "Watching" : "Watch"}
            </button>
          </p>
        </div>
        {!failed && periods !== null && (
          <div
            role="tablist"
            aria-label="Quarters"
            className="pill-tabs card-inset max-w-full p-1"
          >
            {periods.map((period) => {
              const active = period.period_end === selected;
              return (
                <button
                  key={period.period_end}
                  role="tab"
                  aria-selected={active}
                  onClick={() => setSelected(period.period_end)}
                  className="pill-tab text-[14px] aria-selected:bg-surface"
                >
                  {formatPeriod(period.period_end)}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {failed && (
        <ErrorLine
          title="The data service is waking up."
          onRetry={() => setAttempt((n) => n + 1)}
        >
          This can take up to a minute. Then try again.
        </ErrorLine>
      )}

      {!failed && periods === null && (
        <LoadingLine text="Opening the Sleep Number case file." />
      )}

      {!failed && periods !== null && (
        <>
          {points && points.length > 0 && (
            <Reveal onLoad delay={80}>
              <section aria-label="Headroom chart" className="card grain overflow-hidden p-5 sm:p-7">
                <p className="eyebrow">
                  Net leverage ratio per quarter against the covenant limit
                </p>
                <div className="mt-4">
                  <HeadroomChart points={points} />
                </div>
              </section>
            </Reveal>
          )}

          {!visibleDetail && <LoadingLine text="Reading this quarter." />}

          {visibleDetail && (
            <div role="tabpanel" className="space-y-5">
              <Reveal onLoad delay={160}>
                <section aria-label="Verdict" className="card p-5 sm:p-7">
                  <VerdictBlock detail={visibleDetail} />
                  <CaseRequestButton
                    key={visibleDetail.period_end}
                    ticker={ticker}
                    periodEnd={visibleDetail.period_end}
                  />
                </section>
              </Reveal>
              <Reveal>
                <section aria-label="What-if" className="card p-5 sm:p-7">
                  <WhatIfPanel detail={visibleDetail} />
                </section>
              </Reveal>

              <Reveal>
                <Panel
                  id="components"
                  title="Components"
                  description="Select any figure or source to read its evidence in the margin."
                >
                  <ComponentsSection
                    key={visibleDetail.period_end}
                    detail={visibleDetail}
                  />
                </Panel>
              </Reveal>

              <Reveal>
                <Panel id="flags" title="Flags">
                  <FlagsPanel detail={visibleDetail} />
                </Panel>
              </Reveal>

              <Reveal>
                <Panel id="cure" title="Cure">
                  <CurePanel detail={visibleDetail} />
                </Panel>
              </Reveal>

              <Reveal>
                <Panel id="projection" title="Projection">
                  <ProjectionPanel detail={visibleDetail} />
                </Panel>
              </Reveal>

              <Reveal>
                <Panel
                  id="filed-since"
                  title="Filed since this check"
                  description="10-K, 10-Q and 8-K filings after the test date, from the filings Onya already holds."
                >
                  <FiledSinceList
                    key={visibleDetail.period_end}
                    ticker={ticker}
                    date={visibleDetail.period_end}
                  />
                </Panel>
              </Reveal>
            </div>
          )}
        </>
      )}
    </div>
  );
}
