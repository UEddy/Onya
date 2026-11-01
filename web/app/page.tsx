"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  HeadroomChart,
  loadHeadroomPoints,
  type HeadroomPoint,
} from "../components/headroom-chart";
import {
  ErrorLine,
  LoadingLine,
  StatusMark,
} from "../components/site";
import FadeUp from "../components/fade-up";
import {
  ComponentsSection,
  ProjectionPanel,
  VerdictBlock,
} from "../components/case-view";
import WhatIfPanel from "../components/what-if";
import { EvidencePanel } from "../components/evidence";
import { MemoActions, MemoView } from "../components/memo";
import { MarketingShell } from "../components/marketing";
import { stepSentence } from "../lib/step-sentences";
import {
  apiGet,
  formatDateLong,
  formatRatio,
  formatShortMoney,
  type Backtest,
  type PeriodDetail,
  type PeriodSummary,
  type SampleMemo,
} from "../lib/api";

const TABS = [
  { id: "read", index: "01 / Read", caption: "Muse Spark reads the full credit agreement in one pass and quotes each term verbatim." },
  { id: "recalculate", index: "02 / Recalculate", caption: "Python, not the model, rebuilds each ratio from XBRL and earnings release figures." },
  { id: "project", index: "03 / Project", caption: "Onya projects the next test from the trend and flags the risk." },
  { id: "cure", index: "04 / Cure", caption: "Size the fix before the call with the borrower." },
  { id: "memo", index: "05 / Memo", caption: "A memo for the credit analyst, each number checked." },
] as const;

type TabId = (typeof TABS)[number]["id"];

const FAQS: { q: string; a: string }[] = [
  {
    q: "Where do the numbers come from?",
    a: "SEC filings: XBRL data in 10-K and 10-Q reports, earnings release tables, and the credit agreement exhibits on EDGAR. Each figure on the case page links to its source.",
  },
  {
    q: "Does the AI do the math?",
    a: "No. Muse Spark reads the agreement and extracts the terms with verbatim quotes. The ratios, caps, cures and projections are computed in Python.",
  },
  {
    q: "What if the model misreads a clause?",
    a: "Each extracted quote must appear word for word in the filing, or it is flagged. The reviewed extraction is frozen and checked by tests.",
  },
  {
    q: "Which Meta models does Onya use?",
    a: "Muse Spark 1.3 extracts the credit agreement and runs the agent. Muse Spark Open, an open-weights model served on Baseten, ran the back-test extraction across eleven other borrowers.",
  },
  {
    q: "Can it see information from after the test date?",
    a: "No. Each check has an as-of date, and the agent only uses filings dated on or before it.",
  },
  {
    q: "What does a lender get?",
    a: "The covenant results, the cure sized in dollars, the outlook for the next test, and a memo with recommended lender actions.",
  },
];

export default function LandingPage() {
  const [points, setPoints] = useState<HeadroomPoint[] | null>(null);
  const [backtest, setBacktest] = useState<Backtest | null>(null);
  const [periods, setPeriods] = useState<PeriodSummary[] | null>(null);
  const [detail, setDetail] = useState<PeriodDetail | null>(null);
  const [janDetail, setJanDetail] = useState<PeriodDetail | null>(null);
  const [sample, setSample] = useState<SampleMemo | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [tab, setTab] = useState<TabId>("read");
  const [openFaq, setOpenFaq] = useState<number | null>(null);
  const [showClause, setShowClause] = useState(false);
  const [panelHeight, setPanelHeight] = useState<number | undefined>(
    undefined,
  );
  const panelInnerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const inner = panelInnerRef.current;
    if (!inner) return;
    const measure = () => setPanelHeight(inner.offsetHeight);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(inner);
    return () => observer.disconnect();
  });
  const [replayCount, setReplayCount] = useState(1);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      loadHeadroomPoints(),
      apiGet<Backtest>("/backtest"),
      apiGet<{ periods: PeriodSummary[] }>("/company/SNBR/periods"),
      apiGet<PeriodDetail>("/company/SNBR/period/2026-04-04"),
      apiGet<PeriodDetail>("/company/SNBR/period/2026-01-03"),
      apiGet<SampleMemo>("/samples/memo"),
    ]).then(
      ([chart, bt, per, det, jan, memo]) => {
        if (cancelled) return;
        setPoints(chart);
        setBacktest(bt);
        setPeriods(
          [...per.periods].sort((a, b) =>
            a.period_end < b.period_end ? -1 : 1,
          ),
        );
        setDetail(det);
        setJanDetail(jan);
        setSample(memo);
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

  const steps = sample?.steps ?? [];
  useEffect(() => {
    if (!steps.length) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const done = window.setTimeout(() => setReplayCount(steps.length), 0);
      return () => window.clearTimeout(done);
    }
    const timer = setInterval(() => {
      setReplayCount((n) => {
        if (n >= steps.length) {
          clearInterval(timer);
          return n;
        }
        return n + 1;
      });
    }, 700);
    return () => clearInterval(timer);
  }, [steps.length]);

  const ready = points && backtest && periods && detail && sample;
  const d = backtest?.disclosed.totals;
  const t = backtest?.terms.totals;
  const summaryParagraph = sample
    ? (sample.memo.split("\n").find((line) => line.startsWith("Sleep Number fails")) ?? "")
    : "";
  const disallowed = detail?.components.find((c) =>
    c.name.startsWith("Disallowed"),
  );

  const onTabKeyDown = (event: React.KeyboardEvent, index: number) => {
    let next: number | null = null;
    if (event.key === "ArrowRight") next = (index + 1) % TABS.length;
    if (event.key === "ArrowLeft")
      next = (index - 1 + TABS.length) % TABS.length;
    if (next === null) return;
    event.preventDefault();
    setTab(TABS[next].id);
    tabRefs.current[next]?.focus();
  };

  return (
    <MarketingShell>
    <div className="pb-8">
      <div className="border-b border-rule py-10 text-center">
        <h1 className="mx-auto max-w-[900px]">
          <span className="block text-[40px] font-semibold leading-[1.05] tracking-tight sm:text-[60px]">
            Your borrower passed. Barely.
          </span>
          <span className="mt-4 block text-[19px] leading-snug text-ink-muted sm:text-[23px]">
            Onya finds what the compliance certificate glosses over: add-backs
            past the cap, savings still waiting on approval, and the quarter
            it breaks.
          </span>
        </h1>
        <div className="mt-7 flex flex-wrap justify-center gap-3">
          <Link
            href="/app/watchlist"
            className="border border-ink bg-ink px-5 py-2 text-[15px] font-medium text-paper"
          >
            Get started
          </Link>
          <Link
            href="/app/company/SNBR"
            className="border border-ink px-5 py-2 text-[15px] font-medium"
          >
            See the Sleep Number case
          </Link>
        </div>
        <p className="mt-4 text-[13px] text-ink-muted">
          Public SEC data. No sign-up.
        </p>
        {detail && (
          <Link
            href="/app/company/SNBR"
            className="mx-auto mt-8 block max-w-[560px] border border-rule bg-surface p-5 text-left"
          >
            <p className="text-[15px] font-semibold">Sleep Number</p>
            <p className="mt-1 text-[13px] text-ink-muted">
              Net leverage, quarter ended {formatDateLong(detail.period_end)}
            </p>
            <p className="mt-3 text-[44px] font-semibold leading-none">
              {formatRatio(detail.net_leverage.ratio_2dp ?? detail.net_leverage.ratio)}
            </p>
            <p className="mt-2 text-[15px]">
              Limit {formatRatio(detail.net_leverage.threshold)}{" "}
              <StatusMark tone="breach" word="Breach" />
            </p>
            {(detail.scenarios ?? []).length > 0 && (
              <p className="mt-2 text-[13px] text-ink-muted">
                {formatRatio(
                  [...(detail.scenarios ?? [])].sort(
                    (a, b) => b.savings - a.savings,
                  )[0].net_leverage.ratio_2dp,
                )}{" "}
                even with{" "}
                {formatShortMoney(
                  Math.max(...(detail.scenarios ?? []).map((s) => s.savings)),
                )}{" "}
                of projected savings
              </p>
            )}
          </Link>
        )}
      </div>

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
          <FadeUp>
            <section aria-label="Sleep Number chart" className="border-b border-rule py-8">
              <p className="text-[13px] text-ink-muted">
                Net leverage ratio per quarter against the covenant limit
              </p>
              <div className="mt-4">
                <HeadroomChart points={points} />
              </div>
            </section>
          </FadeUp>

          <FadeUp>
            <section aria-label="Proof" className="grid gap-6 border-b border-rule py-8 sm:grid-cols-3">
              <Link href="/accuracy" className="underline decoration-rule underline-offset-4 hover:decoration-ink">
                <span className="text-[22px] font-semibold">
                  {d?.matched} of {d?.covenants}
                </span>{" "}
                disclosed covenant figures matched
              </Link>
              <Link href="/accuracy" className="underline decoration-rule underline-offset-4 hover:decoration-ink">
                <span className="text-[22px] font-semibold">
                  {t?.matched} of {t?.matched}
                </span>{" "}
                contract thresholds correct where the governing agreement was
                found
              </Link>
              <Link href="/accuracy" className="underline decoration-rule underline-offset-4 hover:decoration-ink">
                <span className="text-[22px] font-semibold">
                  {sample.figures_checked} of {sample.figures_checked}
                </span>{" "}
                memo figures traced to tool output
              </Link>
            </section>
          </FadeUp>

          <FadeUp>
            <section id="how-it-works" aria-labelledby="how-heading" className="scroll-mt-4 border-b border-rule py-12">
              <h2 id="how-heading" className="text-[26px] font-semibold tracking-tight">
                How it works
              </h2>
              <div role="tablist" aria-label="How it works" className="mt-4 flex flex-wrap gap-x-6 border-b border-rule">
                {TABS.map((item, index) => (
                  <button
                    key={item.id}
                    ref={(el) => {
                      tabRefs.current[index] = el;
                    }}
                    role="tab"
                    id={`tab-${item.id}`}
                    aria-selected={tab === item.id}
                    aria-controls={`panel-${item.id}`}
                    tabIndex={tab === item.id ? 0 : -1}
                    onClick={() => setTab(item.id)}
                    onKeyDown={(event) => onTabKeyDown(event, index)}
                    className={`index-label border-b-2 py-3 text-[13px] ${
                      tab === item.id
                        ? "border-ink font-semibold"
                        : "border-transparent text-ink-muted hover:text-ink"
                    }`}
                  >
                    {item.index}
                  </button>
                ))}
              </div>
              {TABS.filter((item) => item.id === tab).map((item) => (
                <div
                  key={item.id}
                  style={
                    panelHeight !== undefined
                      ? { height: panelHeight }
                      : undefined
                  }
                  className="overflow-hidden transition-[height] duration-200 motion-reduce:transition-none"
                >
                <div
                  ref={panelInnerRef}
                  role="tabpanel"
                  id={`panel-${item.id}`}
                  aria-labelledby={`tab-${item.id}`}
                  className="pt-6"
                >
                  <p className="max-w-[75ch] text-[15px]">{item.caption}</p>
                  <div className="mt-5">
                    {item.id === "read" && detail && (
                      <div className="space-y-5">
                        {detail.covenant_clause?.quote && (
                          <div>
                            <p className="text-[13px] font-medium">
                              Net Leverage covenant
                              {detail.covenant_clause.section
                                ? `, section ${detail.covenant_clause.section}`
                                : ""}
                            </p>
                            {(() => {
                              const quote = detail.covenant_clause.quote ?? "";
                              const fullMonths = [
                                "January", "February", "March", "April",
                                "May", "June", "July", "August",
                                "September", "October", "November", "December",
                              ];
                              const parts = detail.period_end.split("-");
                              const fullDate = `${fullMonths[Number(parts[1]) - 1]} ${Number(parts[2])}, ${parts[0]}`;
                              const core = `${(detail.net_leverage.threshold ?? 0).toFixed(2)} to 1.00 for the Quarterly Reporting Period ending ${fullDate}`;
                              const at = quote.indexOf(core);
                              const marker =
                                at > 0
                                  ? quote.lastIndexOf("(", at)
                                  : -1;
                              const start =
                                marker >= 0 && at - marker <= 12
                                  ? marker
                                  : at;
                              const excerpt =
                                at >= 0 ? quote.slice(start, at + core.length) : core;
                              return (
                                <>
                                  <p className="quote mt-2 border-l-2 border-rule pl-3 text-[15px]">
                                    ...{" "}
                                    <mark className="bg-watch/30 px-0.5 text-ink dark:bg-watch/40">
                                      {excerpt}
                                    </mark>
                                    , ...
                                  </p>
                                  <button
                                    type="button"
                                    aria-expanded={showClause}
                                    onClick={() => setShowClause(!showClause)}
                                    className="mt-2 text-[15px] underline decoration-rule underline-offset-4 hover:decoration-ink"
                                  >
                                    {showClause
                                      ? "Hide the full clause"
                                      : "Show the full clause"}
                                  </button>
                                  {showClause && (
                                    <blockquote className="quote mt-2 border-l-2 border-rule pl-3 text-[15px]">
                                      {quote}
                                    </blockquote>
                                  )}
                                </>
                              );
                            })()}
                            <p className="mt-2 text-[13px] text-ink-muted">
                              Limit for this period:{" "}
                              {formatRatio(detail.covenant_clause.threshold)}
                            </p>
                          </div>
                        )}
                        {disallowed && (
                          <EvidencePanel
                            source={disallowed.source}
                            periodEnd={detail.period_end}
                          />
                        )}
                      </div>
                    )}
                    {item.id === "recalculate" && detail && (
                      <div>
                        <VerdictBlock detail={detail} />
                        <ComponentsSection detail={detail} />
                      </div>
                    )}
                    {item.id === "project" && detail && (
                      <ProjectionPanel detail={detail} />
                    )}
                    {item.id === "cure" && detail && (
                      <div className="space-y-5">
                        <WhatIfPanel detail={detail} />
                        {detail.cure && (
                          <p className="max-w-[75ch] text-[15px]">
                            To pass at{" "}
                            {formatRatio(detail.net_leverage.threshold)}, debt
                            must fall by{" "}
                            {formatShortMoney(
                              detail.cure.base.net_leverage?.figures
                                ?.debt_reduction_needed?.value,
                            )}
                            , or by{" "}
                            {formatShortMoney(
                              (detail.cure.proforma_scenarios ?? []).find(
                                (s) => s.savings > 0,
                              )?.net_leverage?.figures
                                ?.debt_reduction_needed?.value,
                            )}{" "}
                            with the{" "}
                            {formatShortMoney(
                              (detail.cure.proforma_scenarios ?? []).find(
                                (s) => s.savings > 0,
                              )?.savings,
                            )}{" "}
                            of projected savings.
                          </p>
                        )}
                      </div>
                    )}
                    {item.id === "memo" && sample && (
                      <div className="memo-print-area">
                        <MemoView
                          answer={sample.memo}
                          figureFields={sample.figure_fields}
                          ticker={sample.ticker}
                          periodEnd={sample.period_end}
                        />
                        <MemoActions
                          answer={sample.memo}
                          ticker={sample.ticker}
                          periodEnd={sample.period_end}
                          timestamp={sample.timestamp}
                          asOf={sample.as_of}
                        />
                      </div>
                    )}
                  </div>
                </div>
                </div>
              ))}
            </section>
          </FadeUp>

          <FadeUp>
            <section id="sleep-number" aria-labelledby="timeline-heading" className="scroll-mt-4 border-b border-rule py-12">
              <h2 id="timeline-heading" className="text-[26px] font-semibold tracking-tight">
                Sleep Number, quarter by quarter.
              </h2>
              <ol className="mt-6 space-y-6">
                {periods.map((period, index) => (
                  <li key={period.period_end} className="grid grid-cols-1 gap-y-1 min-[600px]:grid-cols-[180px_minmax(0,1fr)] min-[600px]:gap-x-4">
                    <span className="index-label filing-date whitespace-nowrap text-[13px] text-ink-muted">
                      {String(index + 1).padStart(2, "0")} / {formatDateLong(period.period_end)}
                    </span>
                    <div>
                      <p className="text-[15px]">
                        Quarter ended {formatDateLong(period.period_end)}: net
                        leverage {formatRatio(period.net_leverage.ratio_2dp ?? period.net_leverage.ratio)}{" "}
                        against limit {formatRatio(period.net_leverage.threshold)}.{" "}
                        <StatusMark
                          tone={period.net_leverage.pass ? "pass" : "breach"}
                          word={period.net_leverage.pass ? "Pass" : "Breach"}
                        />
                      </p>
                      {period.period_end === "2026-01-03" &&
                        janDetail?.sensitivity_without_proforma && (
                          <p className="mt-1 text-[15px] text-ink-muted">
                            Passed only with{" "}
                            {formatShortMoney(
                              janDetail.components.find(
                                (c) => c.name === "Pro forma cost savings",
                              )?.value ?? 0,
                            )}{" "}
                            of projected
                            savings; without savings, net leverage was{" "}
                            {formatRatio(janDetail.sensitivity_without_proforma.net_leverage.ratio_2dp)}.
                          </p>
                        )}
                      {period.period_end === "2026-04-04" &&
                        (period.scenarios ?? []).map((s) => (
                          <p key={s.savings} className="mt-1 text-[15px] text-ink-muted">
                            {s.savings > 0
                              ? `${formatRatio(s.net_leverage.ratio_2dp)} with ${formatShortMoney(s.savings)} of projected savings`
                              : `${formatRatio(s.net_leverage.ratio_2dp)} without projected savings`}
                          </p>
                        ))}
                    </div>
                  </li>
                ))}
                <li className="grid grid-cols-1 gap-y-1 min-[600px]:grid-cols-[180px_minmax(0,1fr)] min-[600px]:gap-x-4">
                  <span className="index-label filing-date whitespace-nowrap text-[13px] text-ink-muted">
                    04 / Apr 28, 2026
                  </span>
                  <p className="text-[15px]">
                    Forbearance agreement and thirteenth amendment filed.{" "}
                    <a
                      href="https://www.sec.gov/Archives/edgar/data/827187/000082718726000035/ex101thirteenthamendmentto.htm"
                      className="underline decoration-rule underline-offset-4 hover:decoration-ink"
                    >
                      Read the filing on SEC.gov
                    </a>
                  </p>
                </li>
                <li className="grid grid-cols-1 gap-y-1 min-[600px]:grid-cols-[180px_minmax(0,1fr)] min-[600px]:gap-x-4">
                  <span className="index-label filing-date whitespace-nowrap text-[13px] text-ink-muted">
                    05 / Jun 12, 2026
                  </span>
                  <p className="text-[15px]">
                    Chapter 11 filing.{" "}
                    <a
                      href="https://www.sec.gov/Archives/edgar/data/827187/000095010326008891/dp248362_8k.htm"
                      className="underline decoration-rule underline-offset-4 hover:decoration-ink"
                    >
                      Read the 8-K on SEC.gov
                    </a>
                  </p>
                </li>
              </ol>
              <p className="mt-6 text-[15px] text-ink-muted">
                Onya flagged high risk from the January numbers, before the
                breach.
              </p>
            </section>
          </FadeUp>

          <FadeUp>
            <section
              aria-labelledby="agent-band-heading"
              className="py-8 px-4 sm:px-6"
              style={{ backgroundColor: "#15222C", color: "#E6ECE9" }}
            >
              <h2 id="agent-band-heading" className="text-[22px] font-semibold tracking-tight">
                The agent, working.
              </h2>
              <ol className="mt-4 space-y-2">
                {steps
                  .slice(0, replayCount)
                  .map((step) => stepSentence(step))
                  .filter(
                    (sentence, i, all) => i === 0 || sentence !== all[i - 1],
                  )
                  .map((sentence, i) => (
                    <li key={i} className="grid grid-cols-[64px_minmax(0,1fr)] gap-x-4 text-[15px]">
                      <span style={{ color: "#9AA9A3" }}>
                        {steps[i]?.timestamp
                          ? steps[i].timestamp.slice(11, 19)
                          : ""}
                      </span>
                      <span>{sentence}</span>
                    </li>
                  ))}
              </ol>
              {summaryParagraph && replayCount >= steps.length && (
                <p className="mt-4 max-w-[75ch] text-[15px]">{summaryParagraph}</p>
              )}
              <div className="mt-5">
                <Link
                  href="/app/agent"
                  className="border border-current px-5 py-2 text-[15px] font-medium"
                >
                  Run it live
                </Link>
              </div>
            </section>
          </FadeUp>

          <FadeUp>
            <section id="questions" aria-labelledby="faq-heading" className="scroll-mt-4 border-b border-rule py-12">
              <h2 id="faq-heading" className="text-[26px] font-semibold tracking-tight">
                Questions
              </h2>
              <div className="mt-4">
                {FAQS.map((faq, i) => (
                  <div key={faq.q} className="border-b border-rule py-3">
                    <button
                      type="button"
                      aria-expanded={openFaq === i}
                      onClick={() => setOpenFaq(openFaq === i ? null : i)}
                      className="flex w-full items-baseline justify-between gap-4 text-left text-[15px] font-medium"
                    >
                      <span>{faq.q}</span>
                      <span aria-hidden="true">{openFaq === i ? "-" : "+"}</span>
                    </button>
                    {openFaq === i && (
                      <p className="mt-2 max-w-[75ch] text-[15px]">{faq.a}</p>
                    )}
                  </div>
                ))}
                <div className="border-b border-rule py-3">
                  <button
                    type="button"
                    aria-expanded={openFaq === FAQS.length}
                    onClick={() =>
                      setOpenFaq(openFaq === FAQS.length ? null : FAQS.length)
                    }
                    className="flex w-full items-baseline justify-between gap-4 text-left text-[15px] font-medium"
                  >
                    <span>How accurate is it?</span>
                    <span aria-hidden="true">
                      {openFaq === FAQS.length ? "-" : "+"}
                    </span>
                  </button>
                  {openFaq === FAQS.length && (
                    <p className="mt-2 max-w-[75ch] text-[15px]">
                      {d?.matched} of {d?.covenants} disclosed covenant figures
                      matched; {t?.matched} of {t?.matched} contract thresholds
                      correct where the governing agreement was found.{" "}
                      {sample.figures_checked} of {sample.figures_checked} memo
                      figures traced to tool output.{" "}
                      <Link href="/accuracy" className="underline decoration-rule underline-offset-4 hover:decoration-ink">
                        How accuracy is measured
                      </Link>
                    </p>
                  )}
                </div>
              </div>
            </section>
          </FadeUp>

          <section className="py-12 text-center">
            <h2 className="text-[40px] font-semibold leading-tight tracking-tight sm:text-[56px]">
              See where your borrower stands.
            </h2>
            <div className="mt-6 flex flex-wrap justify-center gap-3">
              <Link
                href="/app/watchlist"
                className="border border-ink bg-ink px-5 py-2 text-[15px] font-medium text-paper"
              >
                Get started
              </Link>
              <Link
                href="/app/company/SNBR"
                className="border border-ink px-5 py-2 text-[15px] font-medium"
              >
                See the Sleep Number case
              </Link>
            </div>
          </section>
        </>
      )}
    </div>
    </MarketingShell>
  );
}
