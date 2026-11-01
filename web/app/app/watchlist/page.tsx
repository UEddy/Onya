"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ErrorLine,
  LoadingLine,
  StatusMark,
} from "../../../components/site";
import {
  apiGet,
  formatPeriod,
  formatRatio,
  formatSignedRatio,
  type Backtest,
  type CompanyRow,
} from "../../../lib/api";

type Tone = "pass" | "watch" | "breach" | "neutral";

function toneFor(company: CompanyRow): { tone: Tone; word: string } {
  if (company.status === "fail") return { tone: "breach", word: "Breach" };
  if (company.headroom === null || company.headroom === undefined)
    return { tone: "neutral", word: "Unknown" };
  if (company.headroom > 0.5) return { tone: "pass", word: "Pass" };
  if (company.headroom >= 0) return { tone: "watch", word: "Watch" };
  return { tone: "breach", word: "Breach" };
}

export default function HomePage() {
  const router = useRouter();
  const [noticeDismissed, setNoticeDismissed] = useState(true);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      try {
        setNoticeDismissed(
          localStorage.getItem("onya-demo-notice-dismissed") === "1",
        );
      } catch {
        setNoticeDismissed(false);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);
  const dismissNotice = () => {
    setNoticeDismissed(true);
    try {
      localStorage.setItem("onya-demo-notice-dismissed", "1");
    } catch {
      /* storage unavailable: notice hides for this visit */
    }
  };
  const [companies, setCompanies] = useState<CompanyRow[] | null>(null);
  const [backtest, setBacktest] = useState<Backtest | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      apiGet<{ companies: CompanyRow[] }>("/companies"),
      apiGet<Backtest>("/backtest"),
    ]).then(
      ([companyRes, backtestRes]) => {
        if (cancelled) return;
        setCompanies(sortWatchlist(companyRes.companies));
        setBacktest(backtestRes);
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

  const ready = companies !== null && backtest !== null;

  return (
    <div className="pb-8">
      {failed && (
        <ErrorLine
          title="The data did not load."
          onRetry={() => setAttempt((n) => n + 1)}
        >
          Onya could not reach its data service. Check that the API is running
          on port 8000, then try again.
        </ErrorLine>
      )}

      {!failed && !ready && (
        <LoadingLine text="Reading covenant data from SEC filings." />
      )}

      {!failed && ready && (
        <>
          <section aria-label="Watchlist" id="watchlist" className="scroll-mt-4 border-b border-rule py-8">
            <p className="text-[13px] text-ink-muted">
              {companies.length} borrowers, breaches first, then tightest
              headroom first
            </p>
            {!noticeDismissed && companies && (
              <div className="mt-4 flex flex-wrap items-baseline gap-x-4 border border-rule bg-surface px-4 py-3 text-[15px]">
                <p>
                  This is a demo portfolio of {companies.length} public
                  borrowers. Sleep Number is fully worked: open it to trace
                  each figure to its filing, or run the agent.
                </p>
                <Link
                  href="/app/company/SNBR"
                  className="underline decoration-rule underline-offset-4 hover:decoration-ink"
                >
                  Open Sleep Number
                </Link>
                <Link
                  href="/app/agent"
                  className="underline decoration-rule underline-offset-4 hover:decoration-ink"
                >
                  Run the agent
                </Link>
                <button
                  type="button"
                  onClick={dismissNotice}
                  className="text-ink-muted underline decoration-rule underline-offset-4 hover:text-ink"
                >
                  Dismiss
                </button>
              </div>
            )}
            {(() => {
              const passing = (companies ?? [])
                .filter(
                  (c) =>
                    c.status === "pass" &&
                    c.headroom !== null &&
                    c.headroom !== undefined,
                )
                .sort((a, b) => (a.headroom ?? 0) - (b.headroom ?? 0));
              const closest = passing[0];
              const breachCount = (companies ?? []).filter(
                (c) => c.status === "fail",
              ).length;
              return (
                <div className="mt-6 grid gap-4 border-t border-rule pt-4 sm:grid-cols-3">
                  <p>
                    <span className="text-[22px] font-semibold">
                      {companies.length}
                    </span>{" "}
                    borrowers on the watchlist
                  </p>
                  <p>
                    <span className="text-[22px] font-semibold">
                      {breachCount}
                    </span>{" "}
                    borrowers in breach
                  </p>
                  <p>
                    {closest ? (
                      <>
                        <span className="text-[22px] font-semibold">
                          {closest.ticker}{" "}
                          {formatSignedRatio(closest.headroom)}
                        </span>{" "}
                        closest to its limit
                      </>
                    ) : (
                      "No passing borrower has a disclosed headroom"
                    )}
                  </p>
                </div>
              );
            })()}
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[720px] border-collapse text-left text-[13px]">
                <thead>
                  <tr className="border-b border-rule text-ink-muted">
                    <th scope="col" className="py-2 pr-4 font-medium">Ticker</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Company</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Covenant</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Ratio</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Limit</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Headroom</th>
                    <th scope="col" className="py-2 pr-4 font-medium">As of</th>
                    <th scope="col" className="py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {(companies ?? []).map((c) => {
                    const { tone, word } = toneFor(c);
                    return (
                      <tr
                        key={c.ticker}
                        onClick={
                          c.ticker === "SNBR"
                            ? () => router.push("/app/company/SNBR")
                            : undefined
                        }
                        className={`border-b border-rule last:border-0 ${
                          c.ticker === "SNBR" ? "cursor-pointer" : ""
                        }`}
                      >
                        <td className="py-2 pr-4 font-medium">
                          {c.ticker === "SNBR" ? (
                            <Link
                              href="/app/company/SNBR"
                              className="underline decoration-rule underline-offset-4 hover:decoration-ink"
                            >
                              {c.ticker}
                            </Link>
                          ) : (
                            c.ticker
                          )}
                        </td>
                        <td className="py-2 pr-4">{c.name}</td>
                        <td className="py-2 pr-4 text-ink-muted">{c.covenant ?? "Not disclosed"}</td>
                        <td className="py-2 pr-4 text-right">{ratioCell(c)}</td>
                        <td className="py-2 pr-4 text-right">{formatRatio(c.threshold)}</td>
                        <td className="py-2 pr-4 text-right">
                          {headroomCell(c)}
                        </td>
                        <td className="py-2 pr-4 text-ink-muted">
                          {c.as_of ? formatPeriod(c.as_of) : "Not disclosed"}
                        </td>
                        <td className="py-2">
                          <StatusMark tone={tone} word={word} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-[13px] text-ink-muted">
              Sleep Number ratio: 5.06x with maximum projected savings,
              6.58x without.
            </p>
          </section>

          <section aria-labelledby="accuracy-heading" className="py-8">
            <h2 id="accuracy-heading" className="text-[22px] font-semibold tracking-tight">
              Accuracy
            </h2>
            <p className="mt-2 max-w-[75ch] text-[15px]">
              {accuracySentence(backtest)}{" "}
              <Link
                href="/app/accuracy"
                className="underline decoration-rule underline-offset-4 hover:decoration-ink"
              >
                How accuracy is measured
              </Link>
            </p>
          </section>
        </>
      )}
    </div>
  );
}

function headroomCell(company: CompanyRow): string {
  if (
    company.ratio_with_savings !== null &&
    company.ratio_with_savings !== undefined &&
    company.threshold !== null &&
    company.threshold !== undefined
  ) {
    const withSavings = company.threshold - company.ratio_with_savings;
    return `${formatSignedRatio(withSavings)} / ${formatSignedRatio(company.headroom)}`;
  }
  return formatSignedRatio(company.headroom);
}

function ratioCell(company: CompanyRow): string {
  if (
    company.ratio_with_savings !== null &&
    company.ratio_with_savings !== undefined &&
    company.ratio_without_savings !== null &&
    company.ratio_without_savings !== undefined
  ) {
    return `${formatRatio(company.ratio_with_savings)} / ${formatRatio(company.ratio_without_savings)}`;
  }
  return formatRatio(company.ratio);
}

function sortWatchlist(companies: CompanyRow[]): CompanyRow[] {
  return [...companies].sort((a, b) => {
    const aBreach = a.status === "fail" ? 0 : 1;
    const bBreach = b.status === "fail" ? 0 : 1;
    if (aBreach !== bBreach) return aBreach - bBreach;
    if (a.headroom === null || a.headroom === undefined) return 1;
    if (b.headroom === null || b.headroom === undefined) return -1;
    return a.headroom - b.headroom;
  });
}

function accuracySentence(backtest: Backtest | null): string {
  if (!backtest) return "";
  const d = backtest.disclosed.totals;
  const t = backtest.terms.totals;
  return (
    `${d.matched} of ${d.covenants} disclosed covenant figures matched, ` +
    `${d.verified} verified by exact quote. Thresholds read from the ` +
    `credit agreements: ${t.matched} of ${t.matched} correct where the ` +
    `governing agreement was found; ${t.amended_after_agreement} later ` +
    `amendments flagged.`
  );
}
