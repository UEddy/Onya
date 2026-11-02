"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ErrorLine,
  LoadingLine,
  Panel,
  StatusPill,
} from "../../../components/site";
import { Reveal } from "../../../components/fade-up";
import {
  apiGet,
  formatDateLong,
  formatPeriod,
  formatRatio,
  formatSignedRatio,
  type Backtest,
  type CompanyRow,
} from "../../../lib/api";
import { useWatch } from "../../../lib/watch";

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
  const { watched, toggle } = useWatch();
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
    <div className="pb-10">
      {failed && (
        <ErrorLine
          title="The data service is waking up."
          onRetry={() => setAttempt((n) => n + 1)}
        >
          This can take up to a minute. Then try again.
        </ErrorLine>
      )}

      {!failed && !ready && (
        <LoadingLine text="Reading covenant data from SEC filings." />
      )}

      {!failed && ready && (
        <div className="space-y-5 pt-6">
          <section aria-label="Watchlist" id="watchlist" className="scroll-mt-24 space-y-5">
            {!noticeDismissed && companies && (
              <div
                className="enter flex flex-wrap items-center gap-x-4 gap-y-2 rounded-2xl px-5 py-3.5 text-[15px] shadow-[0_10px_24px_-16px_var(--shadow-float)]"
                style={{
                  background: "var(--banner-bg)",
                  color: "var(--banner-ink)",
                }}
              >
                <p className="min-w-0 flex-1 basis-[420px]">
                  This is a demo portfolio of {companies.length} public
                  borrowers. Sleep Number is fully worked: open it to trace
                  each figure to its filing, or run the agent.
                </p>
                <Link
                  href="/app/company/SNBR"
                  className="font-medium underline decoration-current/40 underline-offset-4 hover:decoration-current"
                >
                  Open Sleep Number
                </Link>
                <Link
                  href="/app/agent"
                  className="font-medium underline decoration-current/40 underline-offset-4 hover:decoration-current"
                >
                  Run the agent
                </Link>
                <button
                  type="button"
                  onClick={dismissNotice}
                  className="rounded-full px-2.5 py-0.5 text-[13px] hover:bg-black/10"
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
              const tiles = [
                {
                  big: String(companies.length),
                  text: "borrowers on the watchlist",
                },
                {
                  big: String(breachCount),
                  text: "borrowers in breach",
                  tone: "breach" as const,
                },
                closest
                  ? {
                      big: `${closest.ticker} ${formatSignedRatio(closest.headroom)}`,
                      text: "closest to its limit",
                      tone: "watch" as const,
                    }
                  : {
                      big: "",
                      text: "No passing borrower has a disclosed headroom",
                    },
              ];
              return (
                <div className="grid gap-4 sm:grid-cols-3">
                  {tiles.map((tile, i) => (
                    <Reveal key={tile.text} onLoad delay={i * 90}>
                      <div className="card lift grain h-full overflow-hidden p-5 sm:p-6">
                        <p className="flex items-center gap-2 text-[36px] font-semibold leading-none tracking-tight">
                          {tile.tone && (
                            <span
                              aria-hidden="true"
                              className={`dot ${tile.tone === "breach" ? "bg-breach" : "bg-watch"}`}
                            />
                          )}
                          {tile.big}
                        </p>
                        <p className="mt-3 text-[15px] text-ink-muted">{tile.text}</p>
                      </div>
                    </Reveal>
                  ))}
                </div>
              );
            })()}
            <Reveal onLoad delay={260}>
              <div className="card overflow-hidden p-2 sm:p-3">
                <p className="px-3 pb-2 pt-3 text-[13px] text-ink-muted">
                  {companies.length} borrowers, breaches first, then tightest
                  headroom first
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[720px] border-separate border-spacing-0 text-left text-[13px]">
                    <thead>
                      <tr className="text-ink-muted">
                        <th scope="col" className="border-b border-hairline px-3 py-2.5 font-medium">Watch</th>
                        <th scope="col" className="border-b border-hairline px-3 py-2.5 font-medium">Ticker</th>
                        <th scope="col" className="border-b border-hairline px-3 py-2.5 font-medium">Company</th>
                        <th scope="col" className="border-b border-hairline px-3 py-2.5 font-medium">Covenant</th>
                        <th scope="col" className="border-b border-hairline px-3 py-2.5 text-right font-medium">Ratio</th>
                        <th scope="col" className="border-b border-hairline px-3 py-2.5 text-right font-medium">Limit</th>
                        <th scope="col" className="border-b border-hairline px-3 py-2.5 text-right font-medium">Headroom</th>
                        <th scope="col" className="border-b border-hairline px-3 py-2.5 font-medium">As of</th>
                        <th scope="col" className="border-b border-hairline px-3 py-2.5 font-medium">Status</th>
                        <th scope="col" className="border-b border-hairline px-3 py-2.5 font-medium">Next test</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(companies ?? []).map((c) => {
                        const { tone, word } = toneFor(c);
                        const linked = c.ticker === "SNBR";
                        const watching = watched.includes(c.ticker);
                        return (
                          <tr
                            key={c.ticker}
                            onClick={
                              linked
                                ? () => router.push("/app/company/SNBR")
                                : undefined
                            }
                            className={`group ${linked ? "cursor-pointer" : ""}`}
                          >
                            <td className={`border-b border-hairline px-3 py-3 group-last:border-0 ${linked ? "rounded-l-xl group-hover:bg-inset" : ""}`}>
                              <button
                                type="button"
                                aria-pressed={watching}
                                aria-label={watching ? `Stop watching ${c.ticker}` : `Watch ${c.ticker}`}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  toggle(c.ticker);
                                }}
                                className="text-link text-[13px] underline decoration-hairline underline-offset-4 hover:text-ink"
                              >
                                {watching ? "Watching" : "Watch"}
                              </button>
                            </td>
                            <td className={`border-b border-hairline px-3 py-3 font-medium group-last:border-0 ${linked ? "group-hover:bg-inset" : ""}`}>
                              {linked ? (
                                <Link
                                  href="/app/company/SNBR"
                                  className="text-link"
                                >
                                  {c.ticker}
                                </Link>
                              ) : (
                                c.ticker
                              )}
                            </td>
                            <td className={`border-b border-hairline px-3 py-3 group-last:border-0 ${linked ? "group-hover:bg-inset" : ""}`}>{c.name}</td>
                            <td className={`border-b border-hairline px-3 py-3 text-ink-muted group-last:border-0 ${linked ? "group-hover:bg-inset" : ""}`}>{c.covenant ?? "Not disclosed"}</td>
                            <td className={`border-b border-hairline px-3 py-3 text-right group-last:border-0 ${linked ? "group-hover:bg-inset" : ""}`}>{ratioCell(c)}</td>
                            <td className={`border-b border-hairline px-3 py-3 text-right group-last:border-0 ${linked ? "group-hover:bg-inset" : ""}`}>{formatRatio(c.threshold)}</td>
                            <td className={`border-b border-hairline px-3 py-3 text-right group-last:border-0 ${linked ? "group-hover:bg-inset" : ""}`}>
                              {headroomCell(c)}
                            </td>
                            <td className={`border-b border-hairline px-3 py-3 text-ink-muted group-last:border-0 ${linked ? "group-hover:bg-inset" : ""}`}>
                              {c.as_of ? formatPeriod(c.as_of) : "Not disclosed"}
                            </td>
                            <td className={`border-b border-hairline px-3 py-3 group-last:border-0 ${linked ? "group-hover:bg-inset" : ""}`}>
                              <StatusPill tone={tone} word={word} />
                            </td>
                            <td className={`border-b border-hairline px-3 py-3 text-ink-muted group-last:border-0 ${linked ? "rounded-r-xl group-hover:bg-inset" : ""}`}>
                              {nextTestCell(c)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="px-3 pb-3 pt-2 text-[13px] text-ink-muted">
                  Sleep Number ratio: 5.06x with maximum projected savings,
                  6.58x without.
                </p>
              </div>
            </Reveal>
          </section>

          <Reveal>
            <Panel id="accuracy" title="Accuracy">
              <p className="max-w-[75ch] text-[15px]">
                {accuracySentence(backtest)}
              </p>
              <Link href="/app/accuracy" className="btn btn-secondary btn-sm mt-4">
                How accuracy is measured
              </Link>
            </Panel>
          </Reveal>
        </div>
      )}
    </div>
  );
}

function nextTestCell(company: CompanyRow): string {
  const next = company.next_test;
  if (!next || !next.date) return "";
  const parts = [formatDateLong(next.date)];
  if (next.limit !== null && next.limit !== undefined) {
    parts.push(`${formatRatio(next.limit)} limit`);
  }
  if (next.ratio_2dp !== null && next.ratio_2dp !== undefined) {
    parts.push(`proj ${formatRatio(next.ratio_2dp)}`);
  }
  return parts.join(", ");
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
