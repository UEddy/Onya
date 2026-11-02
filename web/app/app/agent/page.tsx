"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { MemoActions, MemoView } from "../../../components/memo";
import { RequestActions, RequestView } from "../../../components/request";
import { formatClock, formatInt, isWakingStatus, type AgentRunState, type AgentStep } from "../../../lib/api";
import { stepSentence } from "../../../lib/step-sentences";

const PREFILL =
  "Check Sleep Number's covenants as of the April 2026 test and tell me what to do.";

const MAX_RUN_SECONDS = 290;
const STALL_SECONDS = 60;

const TOOL_RUNNING: Record<string, string> = {
  lookup_company: "Identifying the company",
  find_agreements: "Finding the governing agreement",
  extract_covenants: "Reading the credit agreement",
  compute_covenants: "Computing covenants",
  project_next_test: "Projecting the next test",
  cure_analysis: "Sizing the cure",
  draft_memo: "Drafting the memo",
};

const NEXT_RUNNING: Record<string, string> = {
  lookup_company: "Finding the governing agreement",
  find_agreements: "Reading the credit agreement",
  extract_covenants: "Computing covenants",
  compute_covenants: "Projecting the next test",
  project_next_test: "Sizing the cure",
  cure_analysis: "Drafting the memo",
  draft_memo: "Finishing up",
};

function runningSentence(steps: AgentStep[]): string {
  // Steps are logged when a tool finishes, so the status line names what
  // comes after the latest logged step, not the step already in the log.
  const tools = steps.filter((s) => s.type === "tool_call" && s.tool);
  const last = tools[tools.length - 1]?.tool ?? null;
  if (last && NEXT_RUNNING[last]) return NEXT_RUNNING[last];
  if (last && TOOL_RUNNING[last]) return TOOL_RUNNING[last];
  if (steps.length === 0) return "Starting the check";
  return "Working through the check";
}

function friendlyError(status: number, detail: string): string {
  if (status === 503 || detail.includes("paused")) {
    return "The live agent is paused. See a saved run.";
  }
  if (detail.includes("daily token budget")) {
    return "The daily token budget is used up for today. See a saved run.";
  }
  if (status === 429) {
    if (detail.includes("hour")) {
      return "Onya allows five checks per hour from each visitor. This one will have to wait an hour.";
    }
    return "Onya allows thirty checks per day in total. Please try again tomorrow.";
  }
  if (status === 413 || status === 422) {
    return "That question needs trimming: keep it under 4,000 characters and non-empty.";
  }
  if (isWakingStatus(status)) {
    return "The data service is waking up. This can take up to a minute. See a saved run.";
  }
  return "The check could not start. Please try again in a moment.";
}

export default function AgentPage() {
  const [question, setQuestion] = useState(PREFILL);
  const [run, setRun] = useState<AgentRunState | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [stalledStep, setStalledStep] = useState<string | null>(null);
  const startedAt = useRef<number | null>(null);
  const lastStepCount = useRef(0);
  const lastProgressAt = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const noteProgress = useCallback(() => {
    lastProgressAt.current = Date.now();
    setStalledStep(null);
  }, []);

  useEffect(() => {
    if (!running) return;
    const tick = setInterval(() => {
      const now = Date.now();
      if (startedAt.current) {
        const secs = Math.floor((now - startedAt.current) / 1000);
        setElapsed(secs);
        if (secs > MAX_RUN_SECONDS) {
          abortRef.current?.abort();
          setRunning(false);
          setError(
            "The check took too long without finishing, so Onya stopped waiting. Nothing was completed. Please try again.",
          );
          return;
        }
      }
      if (
        lastProgressAt.current &&
        now - lastProgressAt.current >= STALL_SECONDS * 1000
      ) {
        setStalledStep((current) => current ?? runningSentence(run?.steps ?? []));
      } else if (stalledStep) {
        setStalledStep(null);
      }
    }, 1000);
    return () => clearInterval(tick);
  }, [running, run, stalledStep]);

  const applyEvent = useCallback(
    (event: unknown) => {
      if (typeof event !== "object" || event === null) return;
      const record = event as Record<string, unknown>;
      if (record.type === "run_result") {
        const reason = typeof record.reason === "string" ? record.reason : "";
        if (reason === "done" || reason === "replay") {
          setRun((current) => ({
            run_id: "",
            error: null,
            status: "done",
            reason,
            steps: current?.steps ?? [],
            answer:
              typeof record.answer === "string" ? record.answer : "",
            total_tokens:
              typeof record.total_tokens === "number"
                ? record.total_tokens
                : 0,
            tool_calls:
              typeof record.tool_calls === "number" ? record.tool_calls : 0,
            figure_fields: Array.isArray(record.figure_fields)
              ? (record.figure_fields as AgentRunState["figure_fields"])
              : [],
            info_request:
              typeof record.info_request === "string"
                ? record.info_request
                : null,
          }));
          setRunning(false);
        } else {
          setRunning(false);
          setError(
            typeof record.answer === "string" && record.answer
              ? record.answer
              : "The check did not finish. Please try again.",
          );
        }
        return;
      }
      if (record.type === "error") {
        setRunning(false);
        setError(
          typeof record.error === "string" && record.error
            ? record.error
            : "The check was lost. Please run it again.",
        );
        return;
      }
      if (record.tool) {
        const step = record as unknown as AgentStep;
        setRun((current) => ({
          run_id: "",
          error: null,
          status: "running",
          reason: null,
          steps: [...(current?.steps ?? []), step],
          answer: null,
          total_tokens:
            typeof step.total_tokens === "number" ? step.total_tokens : 0,
          tool_calls: current?.tool_calls ?? 0,
          figure_fields: current?.figure_fields ?? [],
        }));
        lastStepCount.current += 1;
        noteProgress();
      }
    },
    [noteProgress],
  );

  const submit = useCallback(async () => {
    if (running || question.trim().length === 0) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setError(null);
    setRun(null);
    setElapsed(0);
    setStalledStep(null);
    startedAt.current = Date.now();
    lastStepCount.current = 0;
    lastProgressAt.current = Date.now();
    try {
      const res = await fetch("/api/agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question.trim() }),
        cache: "no-store",
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        const data = (await res.json().catch(() => ({
          detail: "",
        }))) as { detail?: string };
        setRunning(false);
        setError(friendlyError(res.status, data.detail ?? ""));
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            applyEvent(JSON.parse(line) as unknown);
          } catch {
            /* A partial line waits for the next chunk. */
            buffer = `${line}\n${buffer}`;
            break;
          }
        }
      }
      if (buffer.trim()) {
        try {
          applyEvent(JSON.parse(buffer) as unknown);
        } catch {
          /* Trailing bytes are not a complete event; ignore them. */
        }
      }
    } catch {
      if (controller.signal.aborted) return;
      setRunning(false);
      setError(friendlyError(502, ""));
    }
  }, [question, running, applyEvent]);

  const rawSteps = run?.steps ?? [];
  const seenStepKeys = new Set<string>();
  const steps = rawSteps.filter((step) => {
    if (step.type === "assistant_final") return false;
    if (step.type !== "tool_call") return true;
    const key = `${step.tool ?? ""}:${JSON.stringify(step.arguments ?? {})}`;
    if (seenStepKeys.has(key)) return false;
    seenStepKeys.add(key);
    return true;
  });
  const finished =
    run !== null &&
    (run.status === "done" || run.status === "failed" || run.status === "error");
  const currentStep = runningSentence(steps);

  return (
    <div className="space-y-5 pb-10 pt-6">
      <div className="enter">
        <p className="eyebrow">Muse Spark agent</p>
        <h1 className="mt-2 text-[30px] font-semibold leading-tight tracking-tight sm:text-[36px]">
          Agent
        </h1>
        <p className="mt-2 max-w-[75ch] text-[17px] text-ink-muted">
          Ask about a borrower and Onya will read the agreement, run the
          numbers, and write up what to do.
        </p>
      </div>

      <form
        className="card enter no-print p-2 sm:p-3"
        style={{ ["--reveal-delay" as string]: "100ms" }}
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <div className="card-inset grain p-4 sm:p-5">
          <label htmlFor="agent-question" className="text-[15px] font-medium">
            What should Onya check
          </label>
          <textarea
            id="agent-question"
            rows={3}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            disabled={running}
            className="mt-3 w-full resize-y rounded-xl border border-hairline bg-surface p-3.5 text-[15px] shadow-[0_1px_2px_var(--shadow-soft)] outline-none transition-shadow focus:shadow-[0_0_0_3px_var(--hairline)] disabled:opacity-60"
          />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <p className="text-[13px] text-ink-muted">
              Reads filings dated on or before the test date.
            </p>
            <button
              type="submit"
              disabled={running || question.trim().length === 0}
              className="btn btn-primary"
            >
              {running && (
                <span aria-hidden="true" className="dot animate-pulse bg-paper" />
              )}
              {running ? "Running the check" : "Run the check"}
            </button>
          </div>
        </div>
      </form>

      {error && (
        <div role="alert" className="card enter p-6">
          <p className="flex items-center gap-2 text-[17px] font-medium">
            <span aria-hidden="true" className="dot bg-watch" />
            The check did not run.
          </p>
          <p className="mt-1 max-w-[65ch] text-[15px] text-ink-muted">{error}</p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void submit()}
              className="btn btn-secondary btn-sm"
            >
              Try again
            </button>
            {error.includes("See a saved run") && (
              <Link href="/#how-it-works" className="text-link text-[15px]">
                See a saved run
              </Link>
            )}
          </div>
        </div>
      )}

      {(running || steps.length > 0) && (
        <section
          aria-label="Progress"
          className="enter no-print grain relative overflow-hidden rounded-[22px] p-5 sm:p-7"
          style={{
            backgroundColor: "#15222C",
            color: "#E6ECE9",
            boxShadow: "0 30px 70px -30px var(--shadow-float)",
          }}
        >
          <h2 className="text-[20px] font-semibold tracking-tight">Progress</h2>
          <ol className="mt-4 space-y-2.5">
            {steps.map((step, i) => (
              <li
                key={`${step.step ?? i}-${step.timestamp ?? i}`}
                className="enter grid grid-cols-[72px_minmax(0,1fr)] gap-x-4 text-[15px]"
              >
                <span className="font-mono text-[13px]" style={{ color: "#9AA9A3" }}>
                  {formatClock(step.timestamp)}
                </span>
                <span>{stepSentence(step)}</span>
              </li>
            ))}
          </ol>
          {running && (
            <p
              role="status"
              className="mt-5 inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[13px]"
              style={{ backgroundColor: "#16232C", border: "1px solid #2A3A43", color: "#9AA9A3" }}
            >
              <span aria-hidden="true" className="dot animate-pulse" style={{ backgroundColor: "#D49A3E" }} />
              {stalledStep
                ? `Still working on: ${stalledStep.charAt(0).toLowerCase()}${stalledStep.slice(1)}`
                : `${currentStep}. ${elapsed} seconds elapsed.`}
            </p>
          )}
        </section>
      )}

      {finished && (run.status === "failed" || run.status === "error") && (
        <div role="alert" className="card enter p-6">
          <p className="text-[17px] font-medium">The check failed.</p>
          <p className="mt-1 max-w-[65ch] text-[15px] text-ink-muted">
            {run.error ?? "Something went wrong while running the check."}
          </p>
          <button
            type="button"
            onClick={() => void submit()}
            className="btn btn-secondary btn-sm mt-4"
          >
            Try again
          </button>
        </div>
      )}

      {finished && run.status === "done" && run.answer && (
        <section
          aria-label="Memo"
          className="card enter pop-out memo-print-area p-5 sm:p-8"
          style={{ ["--pop-x" as string]: "0px" }}
        >
          <h2 className="text-[22px] font-semibold tracking-tight">Memo</h2>
          <MemoView
            answer={run.answer}
            figureFields={run.figure_fields}
            ticker="SNBR"
            periodEnd="2026-04-04"
          />
          <MemoActions
            answer={run.answer}
            ticker="SNBR"
            periodEnd="2026-04-04"
            asOf="2026-04-04"
            timestamp={run.steps?.[0]?.timestamp ?? null}
          />
          <p className="no-print mt-6 text-[13px] text-ink-muted">
            {formatInt(run.tool_calls)} tool calls, {formatInt(run.total_tokens)} tokens.
          </p>
        </section>
      )}

      {finished && run.status === "done" && run.info_request && (
        <section
          aria-label="Information request"
          className="card enter pop-out memo-print-area mt-5 p-5 sm:p-8"
          style={{ ["--pop-x" as string]: "0px" }}
        >
          <h2 className="text-[22px] font-semibold tracking-tight">
            Information request
          </h2>
          <p className="mt-1 text-[13px] text-ink-muted">
            Draft. Review before sending. Nothing has been sent anywhere.
          </p>
          <div className="mt-4">
            <RequestView
              request={run.info_request}
              figureFields={run.figure_fields}
              ticker="SNBR"
              periodEnd="2026-04-04"
            />
          </div>
          <RequestActions
            request={run.info_request}
            ticker="SNBR"
            periodEnd="2026-04-04"
          />
        </section>
      )}
    </div>
  );
}
