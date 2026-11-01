"use client";

import { useEffect, useState } from "react";
import { DataNote, ErrorLine, LoadingLine } from "./site";
import { apiGet, formatRatio, type Backtest, type CompanyRow } from "../lib/api";
import { headroomBar } from "../lib/headroom-bar";

function sentenceCase(name: string): string {
  const text = name.trim().toLowerCase();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : name;
}

function YesNo({ value }: { value: boolean }) {
  return (
    <span className={value ? undefined : "text-ink-muted"}>
      {value ? "Yes" : "No"}
    </span>
  );
}

export default function AccuracyView({
  showDataNote = true,
}: {
  showDataNote?: boolean;
}) {
  const [backtest, setBacktest] = useState<Backtest | null>(null);
  const [companies, setCompanies] = useState<CompanyRow[]>([]);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    apiGet<{ companies: CompanyRow[] }>("/companies").then(
      (data) => {
        if (!cancelled) setCompanies(data.companies);
      },
      () => undefined,
    );
    apiGet<Backtest>("/backtest").then(
      (data) => {
        if (cancelled) return;
        setBacktest(data);
        setFailed(false);
      },
      () => {
        if (!cancelled) setFailed(true);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  return (
    <div className="pb-8">
      <div className="border-b border-rule py-8">
        <h1 className="text-[30px] font-semibold tracking-tight">Accuracy</h1>
        <p className="mt-2 max-w-[75ch] text-[17px] text-ink-muted">
          Onya is tested against hand-checked covenant figures and the signed
          credit agreements.
        </p>
        {showDataNote && (
          <div className="mt-3">
            <DataNote />
          </div>
        )}
      </div>

      {failed && (
        <ErrorLine
          title="The tables did not load."
          onRetry={() => setAttempt((n) => n + 1)}
        >
          Onya could not reach its data service. Check that the API is running
          on port 8000, then try again.
        </ErrorLine>
      )}

      {!failed && !backtest && (
        <LoadingLine text="Reading the back-test results." />
      )}

      {!failed && backtest && (
        <>
          <section aria-label="Company cards" className="border-b border-rule py-8">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {[...new Map(backtest.disclosed.rows.map((r) => [r.ticker, r])).values()].map((row) => {
                const company = companies.find((c) => c.ticker === row.ticker);
                const bar = headroomBar(
                  row.actual_ext,
                  row.threshold_ext,
                  row.direction,
                  row.waived_threshold,
                );
                const breach = bar.breach;
                const width = bar.fillPct;
                return (
                  <div key={row.ticker} className="border border-rule bg-surface p-4">
                    <p className="text-[15px] font-semibold">{row.ticker}</p>
                    <p className="text-[13px] text-ink-muted">{company?.name ?? row.ticker}</p>
                    <p className="mt-2 text-[13px]">{sentenceCase(row.covenant)}</p>
                    <p className="mt-1 text-[15px]">
                      {row.actual_ext === null
                        ? "Not disclosed"
                        : row.waived_threshold !== null &&
                            row.waived_threshold !== undefined
                          ? `${formatRatio(row.actual_ext)} vs limit ${formatRatio(row.waived_threshold)}, waived from ${formatRatio(row.threshold_ext)}`
                          : `${formatRatio(row.actual_ext)} vs limit ${formatRatio(row.threshold_ext)}`}
                    </p>
                    <div className="mt-3 h-1 w-full" style={{ background: "var(--rule)" }}>
                      <div
                        className="h-1"
                        style={{
                          width: `${width}%`,
                          background: breach ? "var(--breach)" : "var(--ink-muted)",
                        }}
                      />
                    </div>
                    <p className="mt-2 text-[13px] text-ink-muted">
                      Matched: {row.matched ? "Yes" : "No"} · Verified: {row.verified ? "Yes" : "No"}
                    </p>
                  </div>
                );
              })}
            </div>
          </section>

          <section aria-labelledby="disclosed-heading" className="border-b border-rule py-8">
            <h2 id="disclosed-heading" className="text-[22px] font-semibold tracking-tight">
              Disclosed figures
            </h2>
            <p className="mt-1 max-w-[75ch] text-[13px] text-ink-muted">
              Each ratio and limit Onya extracted, next to the hand-checked
              answer key
            </p>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[760px] border-collapse text-left text-[13px]">
                <thead>
                  <tr className="border-b border-rule text-ink-muted">
                    <th scope="col" className="py-2 pr-4 font-medium">Company</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Covenant</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Onya ratio</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Key ratio</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Onya limit</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Key limit</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Matched</th>
                    <th scope="col" className="py-2 font-medium">Verified</th>
                  </tr>
                </thead>
                <tbody>
                  {backtest.disclosed.rows.map((row, i) => (
                    <tr key={`${row.ticker}-${row.covenant}-${i}`} className="border-b border-rule last:border-0">
                      <td className="py-2 pr-4 font-medium">{row.ticker}</td>
                      <td className="py-2 pr-4">{sentenceCase(row.covenant)}</td>
                      <td className="py-2 pr-4 text-right">{formatRatio(row.actual_ext)}</td>
                      <td className="py-2 pr-4 text-right">{formatRatio(row.actual_key)}</td>
                      <td className="py-2 pr-4 text-right">{formatRatio(row.threshold_ext)}</td>
                      <td className="py-2 pr-4 text-right">{formatRatio(row.threshold_key)}</td>
                      <td className="py-2 pr-4"><YesNo value={row.matched} /></td>
                      <td className="py-2"><YesNo value={row.verified} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 max-w-[75ch] text-[15px]">
              {disclosedTotals(backtest)}
            </p>
            {backtest.disclosed.notes.map((note) => (
              <p key={note} className="mt-1 max-w-[75ch] text-[13px] text-ink-muted">
                {note}
              </p>
            ))}
          </section>

          <section aria-labelledby="terms-heading" className="border-b border-rule py-8">
            <h2 id="terms-heading" className="text-[22px] font-semibold tracking-tight">
              Agreement terms
            </h2>
            <p className="mt-1 max-w-[75ch] text-[13px] text-ink-muted">
              Each covenant limit Onya read in a credit agreement, next to the
              limit the company disclosed
            </p>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[760px] border-collapse text-left text-[13px]">
                <thead>
                  <tr className="border-b border-rule text-ink-muted">
                    <th scope="col" className="py-2 pr-4 font-medium">Company</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Covenant</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Direction</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Agreement limit</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Disclosed limit</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Match</th>
                    <th scope="col" className="py-2 font-medium">Quote verified</th>
                  </tr>
                </thead>
                <tbody>
                  {backtest.terms.rows.map((row, i) => (
                    <tr key={`${row.ticker}-${row.name}-${i}`} className="border-b border-rule last:border-0">
                      <td className="py-2 pr-4 font-medium">{row.ticker}</td>
                      <td className="py-2 pr-4">{sentenceCase(row.name)}</td>
                      <td className="py-2 pr-4">{row.direction === "min" ? "Min" : "Max"}</td>
                      <td className="py-2 pr-4 text-right">{formatRatio(row.agreement_threshold)}</td>
                      <td className="py-2 pr-4 text-right">{formatRatio(row.disclosed_threshold)}</td>
                      <td className="py-2 pr-4"><YesNo value={row.match} /></td>
                      <td className="py-2"><YesNo value={row.quote_verified} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 max-w-[75ch] text-[15px]">
              {termsTotals(backtest)}
            </p>
            {backtest.terms.notes.map((note) => (
              <p key={note} className="mt-1 max-w-[75ch] text-[13px] text-ink-muted">
                {note}
              </p>
            ))}
          </section>

          <section aria-labelledby="methods-heading" className="py-8">
            <h2 id="methods-heading" className="text-[22px] font-semibold tracking-tight">
              How this is measured
            </h2>
            <div className="mt-2 max-w-[75ch] space-y-4 text-[15px]">
              <p>
                For the disclosed figures, Onya reads covenant ratios and
                limits out of earnings releases and filings, then checks each
                one against a hand-checked answer key. A figure counts as
                matched when it equals the key, and as verified when a second
                check confirms the quote it came from.
              </p>
              <p>
                For the agreement terms, Onya reads the covenant limits in the
                signed credit agreement on EDGAR and compares them with the
                limits the company discloses. Some agreements were amended
                after signing, so those terms are counted separately rather
                than as misses.
              </p>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function disclosedTotals(backtest: Backtest): string {
  const t = backtest.disclosed.totals;
  return (
    `${t.covenants} covenants: ${t.actual_matched} ratios matched, ` +
    `${t.threshold_matched} limits matched, ${t.matched_and_verified} ` +
    `matched and verified.`
  );
}

function termsTotals(backtest: Backtest): string {
  const t = backtest.terms.totals;
  return (
    `${t.covenants} terms across ${t.companies} companies: ${t.matched} ` +
    `matched, ${t.amended_after_agreement} amended after the agreement, ` +
    `${t.mismatched} mismatched, ${t.quote_verified} quotes verified.`
  );
}
