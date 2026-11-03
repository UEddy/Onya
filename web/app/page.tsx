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
  StatusPill,
  Statement,
} from "../components/site";
import { Reveal } from "../components/fade-up";
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
  formatPeriod,
  formatRatio,
  formatShortMoney,
  type Backtest,
  type CompanyRow,
  type PeriodDetail,
  type PeriodSummary,
  type SampleMemo,
} from "../lib/api";

const TABS = [
  { id: "read", num: "01", label: "Read", caption: "Muse Spark reads the full credit agreement in one pass and quotes each term verbatim." },
  { id: "recalculate", num: "02", label: "Recalculate", caption: "Python, not the model, rebuilds each ratio from XBRL and earnings release figures." },
  { id: "project", num: "03", label: "Project", caption: "Onya projects the next test from the trend and flags the risk." },
  { id: "cure", num: "04", label: "Cure", caption: "Size the fix before the call with the borrower." },
  { id: "memo", num: "05", label: "Memo", caption: "A memo for the credit analyst, each number checked." },
] as const;

type TabId = (typeof TABS)[number]["id"];

const HIGHLIGHTS = [
  "add-backs past the cap",
  "savings still waiting on approval",
  "the quarter it breaks",
];

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

function companyTone(c: CompanyRow): {
  tone: "pass" | "watch" | "breach" | "neutral";
  word: string;
} {
  if (c.status === "fail") return { tone: "breach", word: "Breach" };
  if (c.headroom === null || c.headroom === undefined)
    return { tone: "neutral", word: "Unknown" };
  if (c.headroom > 0.5) return { tone: "pass", word: "Pass" };
  if (c.headroom >= 0) return { tone: "watch", word: "Watch" };
  return { tone: "breach", word: "Breach" };
}

function ChartSkeleton({ height }: { height: number }) {
  return (
    <div aria-hidden="true" className="flex flex-col justify-center gap-4 px-2" style={{ height }}>
      <div className="skeleton h-2.5 w-2/3" />
      <div className="skeleton h-2.5 w-5/6" />
      <div className="skeleton h-2.5 w-1/2" />
      <div className="mt-6 skeleton h-2.5 w-3/4" />
      <div className="skeleton h-2.5 w-2/5" />
    </div>
  );
}

function FaqRow({
  q,
  open,
  onToggle,
  children,
}: {
  q: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="border-b border-hairline last:border-0">
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-4 rounded-xl px-3 py-4 text-left text-[15px] font-medium transition-colors hover:bg-inset sm:px-5"
      >
        <span>{q}</span>
        <span
          aria-hidden="true"
          className={`text-[18px] leading-none text-ink-muted transition-transform duration-300 ${open ? "rotate-90" : ""}`}
        >
          &rsaquo;
        </span>
      </button>
      {open && (
        <div className="enter px-3 pb-5 sm:px-5" style={{ ["--reveal-delay" as string]: "0ms" }}>
          <p className="max-w-[75ch] text-[15px] text-ink-muted">{children}</p>
        </div>
      )}
    </div>
  );
}

export default function LandingPage() {
  const [points, setPoints] = useState<HeadroomPoint[] | null>(null);
  const [backtest, setBacktest] = useState<Backtest | null>(null);
  const [periods, setPeriods] = useState<PeriodSummary[] | null>(null);
  const [detail, setDetail] = useState<PeriodDetail | null>(null);
  const [janDetail, setJanDetail] = useState<PeriodDetail | null>(null);
  const [sample, setSample] = useState<SampleMemo | null>(null);
  const [companies, setCompanies] = useState<CompanyRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [tab, setTab] = useState<TabId>("read");
  const [openFaq, setOpenFaq] = useState<number | null>(null);
  const [showClause, setShowClause] = useState(false);
  const [highlight, setHighlight] = useState(0);
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
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = setInterval(
      () => setHighlight((n) => (n + 1) % HIGHLIGHTS.length),
      2400,
    );
    return () => clearInterval(timer);
  }, []);

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
    apiGet<{ companies: CompanyRow[] }>("/companies").then(
      (data) => {
        if (!cancelled) setCompanies(data.companies);
      },
      () => undefined,
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
  const bestScenario = detail
    ? [...(detail.scenarios ?? [])].sort((a, b) => b.savings - a.savings)[0]
    : undefined;
  const projection = detail?.projection;
  const activeTab = TABS.find((item) => item.id === tab) ?? TABS[0];

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

  const tickerItems = (hidden: boolean) =>
    (companies ?? []).map((c) => {
      const { tone, word } = companyTone(c);
      const body = (
        <>
          <span className="font-semibold">{c.ticker}</span>
          <span className="text-ink-muted">{c.name}</span>
          <span>
            {formatRatio(c.ratio)}
            <span className="text-ink-muted"> / {formatRatio(c.threshold)}</span>
          </span>
          <StatusMark tone={tone} word={word} />
        </>
      );
      const key = `${hidden ? "copy-" : ""}${c.ticker}`;
      if (c.ticker === "SNBR") {
        const pill =
          "flex items-center gap-3 rounded-full border border-hairline bg-surface px-4 py-2 text-[13px] shadow-[0_1px_2px_var(--shadow-soft)] transition-colors hover:bg-inset";
        const inner = (
          <>
            {body}
            <span className="text-ink-muted">Read the case &rarr;</span>
          </>
        );
        return (
          <li key={key} className="shrink-0 pr-3">
            {hidden ? (
              <span className={pill}>{inner}</span>
            ) : (
              <Link href="/app/company/SNBR" className={pill}>
                {inner}
              </Link>
            )}
          </li>
        );
      }
      return (
        <li
          key={key}
          className="flex shrink-0 items-center gap-3 py-2 pl-4 pr-7 text-[13px]"
        >
          {body}
        </li>
      );
    });

  return (
    <MarketingShell>
      <section className="grid items-center gap-x-12 gap-y-14 pb-6 pt-14 sm:pt-20 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:pt-16">
        <div className="enter">
          <p className="eyebrow">Covenant monitoring for private credit</p>
          <h1 className="mt-4">
            <span className="block text-[40px] font-semibold leading-[1.02] tracking-[-0.035em] sm:text-[60px]">
              Your borrower passed. Barely.
            </span>
            <span className="mt-5 block max-w-[38ch] text-[18px] leading-snug text-ink-muted sm:text-[20px]">
              Onya finds what the compliance certificate glosses over:{" "}
              {HIGHLIGHTS.map((phrase, i) => (
                <span key={phrase}>
                  <span
                    className={`highlight-cycle ${highlight === i ? "text-breach" : ""}`}
                  >
                    {phrase}
                  </span>
                  {i === 0 ? ", " : i === 1 ? ", and " : "."}
                </span>
              ))}
            </span>
          </h1>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/app/watchlist" className="btn btn-primary">
              Get started
            </Link>
            <Link href="/app/company/SNBR" className="btn btn-secondary">
              See the Sleep Number case
              <span aria-hidden="true" className="text-ink-muted">&#8599;</span>
            </Link>
          </div>
          <p className="mt-4 text-[13px] text-ink-muted">
            Public SEC data. No sign-up.
          </p>
        </div>

        <div className="relative pb-24 pt-14 lg:pl-14">
          <div
            className="card enter grain overflow-hidden p-4 sm:p-6"
            style={{ ["--reveal-delay" as string]: "120ms" }}
          >
            <p className="eyebrow">SNBR / Net leverage</p>
            <div className="mt-4">
              {points ? (
                <HeadroomChart points={points} height={260} />
              ) : (
                <ChartSkeleton height={260} />
              )}
            </div>
            <div className="flex h-[96px] items-end justify-end sm:pl-[270px]">
              <ul
                aria-label="Chart key"
                className="hidden flex-wrap justify-end gap-x-4 gap-y-1 text-[12px] text-ink-muted sm:flex"
              >
                <li className="flex items-center gap-1.5">
                  <span aria-hidden="true" className="inline-block h-0.5 w-4 rounded-full bg-ink" />
                  Ratio
                </li>
                <li className="flex items-center gap-1.5">
                  <span aria-hidden="true" className="inline-block w-4 border-t-[1.5px] border-dashed border-ink-muted" />
                  Without projected savings
                </li>
                <li className="flex items-center gap-1.5">
                  <span aria-hidden="true" className="inline-block h-0.5 w-4 rounded-full bg-ink-muted" />
                  Covenant limit
                </li>
              </ul>
            </div>
          </div>

          {detail ? (
            <Link
              href="/app/company/SNBR"
              className="card-float enter pop-out lift absolute bottom-0 left-0 z-10 block w-[min(310px,86%)] p-5 text-left"
              style={{
                ["--reveal-delay" as string]: "480ms",
                ["--pop-x" as string]: "-24px",
              }}
            >
              <div className="flex items-center justify-between gap-3">
                <p className="text-[15px] font-semibold">Sleep Number</p>
                <StatusPill tone="breach" word="Breach" />
              </div>
              <p className="mt-1 text-[13px] text-ink-muted">
                Net leverage, quarter ended {formatDateLong(detail.period_end)}
              </p>
              <p className="mt-3 text-[44px] font-semibold leading-none tracking-tight">
                {formatRatio(detail.net_leverage.ratio_2dp ?? detail.net_leverage.ratio)}
              </p>
              <p className="mt-2 text-[15px]">
                Limit {formatRatio(detail.net_leverage.threshold)}
              </p>
              {bestScenario && (
                <p className="mt-2 text-[13px] text-ink-muted">
                  {formatRatio(bestScenario.net_leverage.ratio_2dp)} even with{" "}
                  {formatShortMoney(bestScenario.savings)} of projected savings
                </p>
              )}
            </Link>
          ) : (
            !failed && (
              <div
                aria-hidden="true"
                className="card-float absolute bottom-0 left-0 z-10 w-[min(310px,86%)] space-y-3 p-5"
              >
                <div className="skeleton h-2.5 w-1/2" />
                <div className="skeleton h-7 w-1/3" />
                <div className="skeleton h-2.5 w-2/3" />
              </div>
            )
          )}

          {projection && (
            <div
              className="card-float enter pop-out absolute right-4 top-0 z-10 max-w-[230px] px-4 py-3"
              style={{
                ["--reveal-delay" as string]: "760ms",
                ["--pop-x" as string]: "18px",
              }}
            >
              <p className="eyebrow">Next test {formatPeriod(projection.next_test)}</p>
              <p className="mt-1.5 flex items-center gap-2 text-[15px] font-semibold">
                {formatRatio(projection.projections.onya.ratio_2dp)}
                <span className="text-[13px] font-normal text-ink-muted">
                  vs {formatRatio(projection.next_threshold)}
                </span>
              </p>
              <p className="mt-1 text-[13px]">
                <StatusMark
                  tone={projection.projections.onya.pass ? "pass" : "breach"}
                  word={projection.projections.onya.pass ? "Pass" : "Projected breach"}
                />
              </p>
            </div>
          )}
        </div>
      </section>

      {companies && companies.length > 0 && (
        <Reveal as="section" ariaLabel="Demo watchlist" className="mt-10">
          <p className="eyebrow text-center">
            Demo watchlist: {companies.length} public borrowers
          </p>
          <div className="marquee mt-5" style={{ ["--marquee-duration" as string]: "60s" }}>
            <ul className="marquee-track items-center">
              {tickerItems(false)}
              <li aria-hidden="true" className="contents">
                <ul className="contents">{tickerItems(true)}</ul>
              </li>
            </ul>
          </div>
        </Reveal>
      )}

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
        <>
          <section
            id="how-it-works"
            aria-labelledby="how-heading"
            className="scroll-mt-28 pt-28 sm:pt-36"
          >
            <Reveal>
              <p className="eyebrow mb-4 text-center">How it works</p>
              <Statement
                id="how-heading"
                lead="Read. Recalculate. Project. Cure."
                rest="Onya rebuilds the covenant test from the filings and shows where each number came from."
              />
            </Reveal>
            <Reveal className="card mt-12 p-2 sm:mt-16 sm:p-3" delay={120}>
              <div role="tablist" aria-label="How it works" className="pill-tabs p-1">
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
                    className="pill-tab"
                  >
                    <span className="index-label text-[11px] text-ink-muted">
                      {item.num}
                    </span>
                    <span className="index-label">{item.label}</span>
                  </button>
                ))}
              </div>
              <div className="card-inset grain mt-2 overflow-hidden px-4 pb-4 pt-5 sm:px-8 sm:pb-8 sm:pt-7">
                <div
                  style={
                    panelHeight !== undefined
                      ? { height: panelHeight }
                      : undefined
                  }
                  className="transition-[height] duration-300 ease-out motion-reduce:transition-none"
                >
                  <div
                    key={activeTab.id}
                    ref={panelInnerRef}
                    role="tabpanel"
                    id={`panel-${activeTab.id}`}
                    aria-labelledby={`tab-${activeTab.id}`}
                    className="pb-1"
                  >
                    <div className="enter">
                      <h3 className="text-[17px] font-semibold tracking-tight">
                        {activeTab.label}
                      </h3>
                      <p className="mt-1 max-w-[65ch] text-[15px] text-ink-muted">
                        {activeTab.caption}
                      </p>
                    </div>
                    <div className="mt-6">
                      {activeTab.id === "read" && detail && (
                        <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
                          {detail.covenant_clause?.quote && (
                            <div
                              className="card-float enter p-5 sm:p-6"
                              style={{ ["--reveal-delay" as string]: "80ms" }}
                            >
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
                                    <p className="quote mt-3 border-l-2 border-rule pl-3 text-[15px]">
                                      ...{" "}
                                      <mark className="rounded bg-watch/30 px-0.5 text-ink dark:bg-watch/40">
                                        {excerpt}
                                      </mark>
                                      , ...
                                    </p>
                                    <button
                                      type="button"
                                      aria-expanded={showClause}
                                      onClick={() => setShowClause(!showClause)}
                                      className="btn btn-secondary btn-sm mt-4"
                                    >
                                      {showClause
                                        ? "Hide the full clause"
                                        : "Show the full clause"}
                                    </button>
                                    {showClause && (
                                      <blockquote className="quote mt-3 border-l-2 border-rule pl-3 text-[15px]">
                                        {quote}
                                      </blockquote>
                                    )}
                                  </>
                                );
                              })()}
                              <p className="mt-4 text-[13px] text-ink-muted">
                                Limit for this period:{" "}
                                {formatRatio(detail.covenant_clause.threshold)}
                              </p>
                            </div>
                          )}
                          {disallowed && (
                            <div
                              className="card-float enter pop-out p-5 sm:p-6 lg:-ml-10 lg:mt-12"
                              style={{
                                ["--reveal-delay" as string]: "260ms",
                                ["--pop-x" as string]: "22px",
                              }}
                            >
                              <p className="eyebrow mb-3">Evidence</p>
                              <EvidencePanel
                                source={disallowed.source}
                                periodEnd={detail.period_end}
                              />
                            </div>
                          )}
                        </div>
                      )}
                      {activeTab.id === "recalculate" && detail && (
                        <div className="space-y-5">
                          <div className="card-float enter p-5 sm:p-6">
                            <VerdictBlock detail={detail} />
                          </div>
                          <div
                            className="card-float enter p-5 sm:p-6"
                            style={{ ["--reveal-delay" as string]: "160ms" }}
                          >
                            <ComponentsSection detail={detail} />
                          </div>
                        </div>
                      )}
                      {activeTab.id === "project" && detail && (
                        <div className="card-float enter p-5 sm:p-6">
                          <ProjectionPanel detail={detail} />
                        </div>
                      )}
                      {activeTab.id === "cure" && detail && (
                        <div className="space-y-5">
                          <div className="card-float enter p-5 sm:p-6">
                            <WhatIfPanel detail={detail} />
                          </div>
                          {detail.cure && (
                            <p
                              className="card-float enter pop-out max-w-[75ch] p-5 text-[15px] sm:ml-10"
                              style={{ ["--reveal-delay" as string]: "220ms" }}
                            >
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
                      {activeTab.id === "memo" && sample && (
                        <div className="card-float enter memo-print-area p-5 sm:p-7">
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
              </div>
            </Reveal>
          </section>

          <section aria-labelledby="proof-heading" className="pt-28 sm:pt-36">
            <Reveal>
              <Statement
                id="proof-heading"
                lead="Checked against the filings."
                rest="Each figure traces to an XBRL fact, an earnings release table or a clause in the credit agreement."
              />
            </Reveal>
            <div className="mt-12 grid gap-4 sm:mt-16 md:grid-cols-3">
              {[
                {
                  big: `${d?.matched} of ${d?.covenants}`,
                  text: "disclosed covenant figures matched",
                },
                {
                  big: `${t?.matched} of ${t?.covenants}`,
                  text: `contract limits matched; ${t?.amended_after_agreement} changed by later amendments, flagged`,
                },
                {
                  big: `${sample.figures_checked} of ${sample.figures_checked}`,
                  text: "memo figures traced to tool output",
                },
              ].map((item, i) => (
                <Reveal key={item.text} delay={i * 120}>
                  <Link
                    href="/accuracy"
                    className="card lift grain flex h-full min-h-[220px] flex-col justify-between overflow-hidden p-6 sm:p-7"
                  >
                    <span className="text-[44px] font-semibold leading-none tracking-tight sm:text-[52px]">
                      {item.big}
                    </span>
                    <span>
                      <span className="block max-w-[28ch] text-[15px]">
                        {item.text}
                      </span>
                      <span className="mt-3 block text-[13px] text-ink-muted">
                        How accuracy is measured &rarr;
                      </span>
                    </span>
                  </Link>
                </Reveal>
              ))}
            </div>
          </section>

          <section
            id="sleep-number"
            aria-labelledby="timeline-heading"
            className="scroll-mt-28 pt-28 sm:pt-36"
          >
            <Reveal>
              <Statement
                id="timeline-heading"
                lead="Sleep Number, quarter by quarter."
                rest="Onya flagged high risk from the January numbers, before the breach."
              />
            </Reveal>
            <ol className="mx-auto mt-12 max-w-[880px] space-y-3 sm:mt-16">
              {periods.map((period, index) => (
                <Reveal as="li" key={period.period_end} delay={index * 80}>
                  <div className="card lift p-5 sm:p-6">
                    <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
                      <div className="min-w-0 flex-1">
                        <p className="text-[15px] font-semibold">
                          Quarter ended {formatDateLong(period.period_end)}
                        </p>
                        <p className="mt-1 text-[15px]">
                          Net leverage {formatRatio(period.net_leverage.ratio_2dp ?? period.net_leverage.ratio)}{" "}
                          against limit {formatRatio(period.net_leverage.threshold)}.
                        </p>
                        {period.period_end === "2026-01-03" &&
                          janDetail?.sensitivity_without_proforma && (
                            <p className="mt-1 text-[14px] text-ink-muted">
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
                            <p key={s.savings} className="mt-1 text-[14px] text-ink-muted">
                              {s.savings > 0
                                ? `${formatRatio(s.net_leverage.ratio_2dp)} with ${formatShortMoney(s.savings)} of projected savings`
                                : `${formatRatio(s.net_leverage.ratio_2dp)} without projected savings`}
                            </p>
                          ))}
                      </div>
                      <div className="flex flex-col items-end gap-2">
                        <span className="index-label filing-date whitespace-nowrap text-[12px] text-ink-muted">
                          {String(index + 1).padStart(2, "0")} / {formatDateLong(period.period_end)}
                        </span>
                        <StatusPill
                          tone={period.net_leverage.pass ? "pass" : "breach"}
                          word={period.net_leverage.pass ? "Pass" : "Breach"}
                        />
                      </div>
                    </div>
                  </div>
                </Reveal>
              ))}
              <Reveal as="li" delay={periods.length * 80}>
                <div className="card lift flex flex-wrap items-start justify-between gap-x-6 gap-y-2 p-5 sm:p-6">
                  <p className="text-[15px]">
                    Forbearance agreement and thirteenth amendment filed.{" "}
                    <a
                      href="https://www.sec.gov/Archives/edgar/data/827187/000082718726000035/ex101thirteenthamendmentto.htm"
                      className="text-link"
                    >
                      Read the filing on SEC.gov
                    </a>
                  </p>
                  <span className="index-label filing-date whitespace-nowrap text-[12px] text-ink-muted">
                    04 / Apr 28, 2026
                  </span>
                </div>
              </Reveal>
              <Reveal as="li" delay={(periods.length + 1) * 80}>
                <div className="card lift flex flex-wrap items-start justify-between gap-x-6 gap-y-2 p-5 sm:p-6">
                  <p className="text-[15px]">
                    Chapter 11 filing.{" "}
                    <a
                      href="https://www.sec.gov/Archives/edgar/data/827187/000095010326008891/dp248362_8k.htm"
                      className="text-link"
                    >
                      Read the 8-K on SEC.gov
                    </a>
                  </p>
                  <span className="index-label filing-date whitespace-nowrap text-[12px] text-ink-muted">
                    05 / Jun 12, 2026
                  </span>
                </div>
              </Reveal>
            </ol>
            <p className="mt-6 text-[15px]">
              <Link href="/app/company/SNBR#rewind" className="text-link">
                Rewind the case: what Onya would have said at each test
              </Link>
            </p>
          </section>

          <section aria-labelledby="agent-band-heading" className="pt-28 sm:pt-36">
            <Reveal>
              <Statement
                id="agent-band-heading"
                lead="The agent, working."
                rest="A saved run, replayed step by step."
              />
            </Reveal>
            <Reveal className="mt-12 sm:mt-16" delay={100}>
              <div
                className="grain relative grid gap-6 overflow-hidden rounded-[22px] p-5 sm:p-8 lg:grid-cols-[minmax(0,1fr)_340px]"
                style={{
                  backgroundColor: "#15222C",
                  color: "#E6ECE9",
                  boxShadow: "0 30px 70px -30px var(--shadow-float)",
                }}
              >
                <ol className="min-h-[220px] space-y-2.5 font-mono text-[13px]">
                  {steps
                    .slice(0, replayCount)
                    .map((step) => stepSentence(step))
                    .filter(
                      (sentence, i, all) => i === 0 || sentence !== all[i - 1],
                    )
                    .map((sentence, i) => (
                      <li
                        key={i}
                        className="enter grid grid-cols-[72px_minmax(0,1fr)] gap-x-4"
                      >
                        <span style={{ color: "#9AA9A3" }}>
                          {steps[i]?.timestamp
                            ? steps[i].timestamp.slice(11, 19)
                            : ""}
                        </span>
                        <span className="font-sans text-[15px]">{sentence}</span>
                      </li>
                    ))}
                </ol>
                <div className="self-end">
                  <div
                    className="rounded-[18px] p-5"
                    style={{
                      backgroundColor: "#16232C",
                      border: "1px solid #2A3A43",
                      boxShadow: "0 24px 50px -20px rgb(0 0 0 / 0.7)",
                    }}
                  >
                    {summaryParagraph && replayCount >= steps.length ? (
                      <p className="enter text-[15px]">{summaryParagraph}</p>
                    ) : (
                      <p className="text-[13px]" style={{ color: "#9AA9A3" }}>
                        Replaying {Math.min(replayCount, steps.length)} of{" "}
                        {steps.length} steps.
                      </p>
                    )}
                    <Link
                      href="/app/agent"
                      className="btn btn-sm mt-4"
                      style={{ backgroundColor: "#E6ECE9", color: "#15222C" }}
                    >
                      Run it live
                    </Link>
                  </div>
                </div>
              </div>
            </Reveal>
          </section>

          <section
            id="questions"
            aria-labelledby="faq-heading"
            className="scroll-mt-28 pt-28 sm:pt-36"
          >
            <Reveal>
              <h2
                id="faq-heading"
                className="text-center text-[15px] font-medium text-ink-muted"
              >
                Questions
              </h2>
            </Reveal>
            <Reveal className="card mx-auto mt-8 max-w-[880px] p-2 sm:p-3" delay={100}>
              {FAQS.map((faq, i) => (
                <FaqRow
                  key={faq.q}
                  q={faq.q}
                  open={openFaq === i}
                  onToggle={() => setOpenFaq(openFaq === i ? null : i)}
                >
                  {faq.a}
                </FaqRow>
              ))}
              <FaqRow
                q="How accurate is it?"
                open={openFaq === FAQS.length}
                onToggle={() =>
                  setOpenFaq(openFaq === FAQS.length ? null : FAQS.length)
                }
              >
                {d?.matched} of {d?.covenants} disclosed covenant figures
                matched; {t?.matched} of {t?.covenants} contract limits
                matched, with {t?.amended_after_agreement} changed by later
                amendments, flagged.{" "}
                {sample.figures_checked} of {sample.figures_checked} memo
                figures traced to tool output.{" "}
                <Link href="/accuracy" className="text-link text-ink">
                  How accuracy is measured
                </Link>
              </FaqRow>
            </Reveal>
          </section>

          <Reveal as="section" className="pt-28 text-center sm:pt-36">
            <h2 className="text-[40px] font-semibold leading-tight tracking-[-0.03em] sm:text-[56px]">
              See where your borrower stands.
            </h2>
            <div className="mt-8 flex flex-wrap justify-center gap-3">
              <Link href="/app/watchlist" className="btn btn-primary">
                Get started
              </Link>
              <Link href="/app/company/SNBR" className="btn btn-secondary">
                See the Sleep Number case
                <span aria-hidden="true" className="text-ink-muted">&#8599;</span>
              </Link>
            </div>
          </Reveal>
        </>
      )}
    </MarketingShell>
  );
}
