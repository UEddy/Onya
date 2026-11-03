"use client";

import { useEffect, useState } from "react";
import { DataNote, ErrorLine, LoadingLine, Panel } from "./site";
import { Reveal } from "./fade-up";
import {
  apiGet,
  formatRatio,
  formatSignedRatio,
  type Backtest,
  type CompanyRow,
} from "../lib/api";
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
    <div className="space-y-5 pb-10 pt-6">
      <div className="enter">
        <p className="eyebrow">Back-test</p>
        <h1 className="mt-2 text-[30px] font-semibold leading-tight tracking-tight sm:text-[36px]">Accuracy</h1>
        <p className="mt-2 max-w-[75ch] text-[17px] text-ink-muted">
          Onya is tested against hand-checked covenant figures and the signed
          credit agreements.
        </p>
        <p className="mt-3 inline-flex items-center gap-2 rounded-full border border-hairline bg-surface px-3 py-1 text-[12px] font-medium">
          <span aria-hidden="true" className="dot bg-pass" />
          Back-test extraction: Built with Muse Spark Open
        </p>
        {showDataNote && (
          <div className="mt-3">
            <DataNote />
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

      {!failed && !backtest && (
        <LoadingLine text="Reading the back-test results." />
      )}

      {!failed && backtest && (
        <>
          <section aria-label="Company cards">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {[...new Map(backtest.disclosed.rows.map((r) => [r.ticker, r])).values()].map((row, index) => {
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
                  <Reveal key={row.ticker} onLoad delay={Math.min(index, 8) * 60}>
                  <div className="card lift h-full p-5">
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
                    <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full" style={{ background: "var(--hairline)" }}>
                      <div
                        className="h-1.5 rounded-full"
                        style={{
                          width: `${width}%`,
                          background: breach ? "var(--breach)" : "var(--ink-muted)",
                        }}
                      />
                    </div>
                    <p className="mt-3 text-[13px] text-ink-muted">
                      Matched: {row.matched ? "Yes" : "No"} · Verified: {row.verified ? "Yes" : "No"}
                    </p>
                  </div>
                  </Reveal>
                );
              })}
            </div>
          </section>

          <Reveal>
          <Panel
            id="disclosed"
            title="Disclosed figures"
            description="Each ratio and limit Onya extracted, next to the hand-checked answer key"
          >
            <div className="card-inset overflow-x-auto px-3 py-1">
              <table className="w-full min-w-[760px] border-collapse text-left text-[13px]">
                <thead>
                  <tr className="border-b border-hairline text-ink-muted">
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
                    <tr key={`${row.ticker}-${row.covenant}-${i}`} className="border-b border-hairline last:border-0">
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
            <p className="mt-4 max-w-[75ch] text-[15px]">
              {disclosedTotals(backtest)}
            </p>
            {backtest.disclosed.notes.map((note) => (
              <p key={note} className="mt-1 max-w-[75ch] text-[13px] text-ink-muted">
                {note}
              </p>
            ))}
          </Panel>
          </Reveal>

          <Reveal>
          <Panel
            id="terms"
            title="Agreement terms"
            description="Each covenant limit Onya read in a credit agreement, next to the limit the company disclosed"
          >
            <div className="card-inset overflow-x-auto px-3 py-1">
              <table className="w-full min-w-[760px] border-collapse text-left text-[13px]">
                <thead>
                  <tr className="border-b border-hairline text-ink-muted">
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
                    <tr key={`${row.ticker}-${row.name}-${i}`} className="border-b border-hairline last:border-0">
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
            <p className="mt-4 max-w-[75ch] text-[15px]">
              {termsTotals(backtest)}
            </p>
            {backtest.terms.notes.map((note) => (
              <p key={note} className="mt-1 max-w-[75ch] text-[13px] text-ink-muted">
                {note}
              </p>
            ))}
          </Panel>
          </Reveal>

          <Reveal>
          <Panel
            id="recompute"
            title="Recomputed from filings"
            description="Each leverage ratio rebuilt from XBRL using the agreement's own definition, next to the ratio the company disclosed"
          >
            <p className="mb-4 max-w-[75ch] text-[15px]">
              {recomputeTotals(backtest)}
            </p>
            <div className="card-inset overflow-x-auto px-3 py-1">
              <table className="w-full min-w-[820px] border-collapse text-left text-[13px]">
                <thead>
                  <tr className="border-b border-hairline text-ink-muted">
                    <th scope="col" className="py-2 pr-4 font-medium">Company</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Covenant</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Recomputed</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Disclosed</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Difference</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Status</th>
                    <th scope="col" className="py-2 font-medium">Not available from filings</th>
                  </tr>
                </thead>
                <tbody>
                  {backtest.recompute.rows.map((row, i) => (
                    <tr key={`${row.ticker}-${row.name}-${i}`} className="border-b border-hairline align-top last:border-0">
                      <td className="py-2 pr-4 font-medium">{row.ticker}</td>
                      <td className="py-2 pr-4">{sentenceCase(row.name)}</td>
                      <td className="py-2 pr-4 text-right">
                        {row.recomputed === null ? "Not computed" : formatRatio(row.recomputed)}
                      </td>
                      <td className="py-2 pr-4 text-right">{formatRatio(row.disclosed)}</td>
                      <td className="py-2 pr-4 text-right">
                        {row.difference === null ? "N/A" : formatSignedRatio(row.difference)}
                      </td>
                      <td className="py-2 pr-4">{RECOMPUTE_STATUS[row.status]}</td>
                      <td className="py-2">
                        {row.missing.length === 0 ? (
                          "None"
                        ) : (
                          <details>
                            <summary className="cursor-pointer">
                              {row.missing.length === 1 ? "1 item" : `${row.missing.length} items`}
                            </summary>
                            <ul className="mt-1 max-w-[52ch] list-disc space-y-1 pl-4 text-ink-muted">
                              {row.missing.map((item) => (
                                <li key={item}>{item}</li>
                              ))}
                            </ul>
                          </details>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {backtest.recompute.notes.map((note) => (
              <p key={note} className="mt-1 max-w-[75ch] text-[13px] text-ink-muted">
                {note}
              </p>
            ))}
          </Panel>
          </Reveal>

          <Reveal>
          <Panel id="methods" title="How this is measured">
            <div className="max-w-[75ch] space-y-4 text-[15px]">
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
              <p>
                For the recomputed ratios, Onya maps each part of the
                agreement&apos;s definition to XBRL facts for the test period.
                Company-specific add-backs and pro forma items are not in XBRL,
                so Onya lists them instead of guessing and marks the result
                partial. A partial figure uses only the parts it could map, so
                it is a reference point rather than a covenant calculation.
                These results are not part of the accuracy totals above.
              </p>
            </div>
          </Panel>
          </Reveal>
        </>
      )}
    </div>
  );
}

const RECOMPUTE_STATUS = {
  match: "Full match",
  partial: "Partial",
  mismatch: "Mismatch",
} as const;

function recomputeTotals(backtest: Backtest): string {
  const t = backtest.recompute.totals;
  return (
    `${t.ratios} ratios across ${t.companies} companies: ${t.full} full ` +
    `matches, ${t.partial} partial, ${t.mismatched} mismatched. ` +
    `${t.numeric} have a figure; the others could not be built from XBRL. ` +
    `A partial figure leaves out the items listed beside it.`
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
    `${t.mismatched} mismatched, ${t.quote_verified} covenant quotes verified.`
  );
}
