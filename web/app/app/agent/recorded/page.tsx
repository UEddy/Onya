"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { MemoView } from "../../../../components/memo";
import { ErrorLine, LoadingLine } from "../../../../components/site";
import { apiGet, formatDateLong, type SampleMemo } from "../../../../lib/api";

/* The saved, verified SNBR run. Always labeled as recorded: nothing here
   ran just now, and only the figure links reach current data. */
export default function RecordedRunPage() {
  const [sample, setSample] = useState<SampleMemo | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    apiGet<SampleMemo>("/samples/memo").then(
      (memo) => {
        if (!cancelled) {
          setSample(memo);
          setFailed(false);
        }
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
        <p className="eyebrow">Muse Spark agent</p>
        <h1 className="mt-2 text-[30px] font-semibold leading-tight tracking-tight sm:text-[36px]">
          Recorded run
        </h1>
        <p className="mt-2 max-w-[75ch] text-[17px] text-ink-muted">
          A saved check, shown when a live one cannot finish. No model ran
          just now.
        </p>
      </div>

      {failed && (
        <ErrorLine
          title="The recorded run could not be loaded."
          onRetry={() => setAttempt((n) => n + 1)}
        >
          Please try again in a moment.
        </ErrorLine>
      )}
      {!failed && !sample && <LoadingLine text="Opening the recorded run." />}

      {sample && (
        <section
          aria-label="Recorded run"
          className="card enter memo-print-area p-5 sm:p-8"
        >
          <p className="inline-flex items-center gap-2 rounded-full border border-hairline bg-inset px-3 py-1 text-[13px] font-medium">
            <span aria-hidden="true" className="dot bg-watch" />
            Recorded run from {formatDateLong(sample.timestamp.slice(0, 10))}
          </p>
          <p className="mt-3 text-[14px] text-ink-muted">
            Run {sample.run_id}. Not a live check.{" "}
            {typeof sample.figures_checked === "number" &&
              `${sample.figures_checked} figures were checked against the tool outputs when it was saved. `}
            Figure links open the current case file.
          </p>
          <h2 className="mt-6 text-[22px] font-semibold tracking-tight">Memo</h2>
          <MemoView
            answer={sample.memo}
            figureFields={sample.figure_fields}
            ticker={sample.ticker}
            periodEnd={sample.period_end}
          />
          <p className="no-print mt-6">
            <Link href="/app/agent" className="btn btn-secondary btn-sm">
              Run a live check
            </Link>
          </p>
        </section>
      )}
    </div>
  );
}
