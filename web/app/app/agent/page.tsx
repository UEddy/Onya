"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { MemoActions, MemoView } from "../../../components/memo";
import { formatClock, formatInt, type AgentRunState, type AgentStep } from "../../../lib/api";
import { stepSentence } from "../../../lib/step-sentences";

const PREFILL =
  "Check Sleep Number's covenants as of the April 2026 test and tell me what to do.";

const MAX_RUN_SECONDS = 240;
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
  if (status === 429) {
    if (detail.includes("hour")) {
      return "Onya allows five checks per hour from each visitor. This one will have to wait an hour.";
    }
    return "Onya allows thirty checks per day in total. Please try again tomorrow.";
  }
  if (status === 413 || status === 422) {
    return "That question needs trimming: keep it under 4,000 characters and non-empty.";
  }
  if (status === 502) {
    return "Onya could not reach its agent service. Check that the API is running on port 8000, then try again.";
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
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedAt = useRef<number | null>(null);
  const lastStepCount = useRef(0);
  const lastProgressAt = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (timer.current) {
      clearInterval(timer.current);
      timer.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  useEffect(() => {
    if (!running) return;
    const tick = setInterval(() => {
      const now = Date.now();
      if (startedAt.current) {
        const secs = Math.floor((now - startedAt.current) / 1000);
        setElapsed(secs);
        if (secs > MAX_RUN_SECONDS) {
          stopPolling();
          setRunning(false);
          setError(
            "The check took longer than four minutes without finishing, so Onya stopped waiting. Nothing was completed. Please try again.",
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
  }, [running, run, stalledStep, stopPolling]);

  const poll = useCallback(
    async (runId: string) => {
      try {
        const res = await fetch(`/api/agent/${runId}`, {
          cache: "no-store",
        });
        const state = (await res.json()) as AgentRunState;
        if (!res.ok) {
          stopPolling();
          setRunning(false);
          setError("The check was lost. Please run it again.");
          return;
        }
        if (state.steps.length !== lastStepCount.current) {
          lastStepCount.current = state.steps.length;
          lastProgressAt.current = Date.now();
          setStalledStep(null);
        }
        setRun(state);
        if (
          state.status === "done" ||
          state.status === "failed" ||
          state.status === "error"
        ) {
          stopPolling();
          setRunning(false);
        }
      } catch {
        stopPolling();
        setRunning(false);
        setError("The check was lost. Please run it again.");
      }
    },
    [stopPolling],
  );

  const submit = useCallback(async () => {
    if (running || question.trim().length === 0) return;
    stopPolling();
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
      });
      const data = (await res.json()) as { run_id?: string; detail?: string };
      if (!res.ok || !data.run_id) {
        setRunning(false);
        setError(friendlyError(res.status, data.detail ?? ""));
        return;
      }
      await poll(data.run_id);
      timer.current = setInterval(() => void poll(data.run_id as string), 2000);
    } catch {
      setRunning(false);
      setError(friendlyError(502, ""));
    }
  }, [question, running, poll, stopPolling]);

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
    <div className="pb-8">
      <div className="border-b border-rule py-8">
        <h1 className="text-[30px] font-semibold tracking-tight">Agent</h1>
        <p className="mt-2 max-w-[75ch] text-[17px] text-ink-muted">
          Ask about a borrower and Onya will read the agreement, run the
          numbers, and write up what to do.
        </p>
      </div>

      <form
        className="no-print border-b border-rule py-8"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label htmlFor="agent-question" className="text-[15px] font-medium">
          What should Onya check
        </label>
        <textarea
          id="agent-question"
          rows={3}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          disabled={running}
          className="mt-2 w-full border border-rule bg-surface p-3 text-[15px] disabled:opacity-60"
        />
        <div className="mt-3">
          <button
            type="submit"
            disabled={running || question.trim().length === 0}
            className="border border-ink px-5 py-2 text-[15px] font-medium disabled:opacity-50"
          >
            {running ? "Running the check" : "Run the check"}
          </button>
        </div>
      </form>

      {error && (
        <div role="alert" className="border-b border-rule py-8">
          <p className="text-[17px] font-medium">The check did not run.</p>
          <p className="mt-1 max-w-[65ch] text-[15px] text-ink-muted">{error}</p>
          <button
            type="button"
            onClick={() => void submit()}
            className="mt-3 text-[15px] underline decoration-rule underline-offset-4 hover:text-ink"
          >
            Try again
          </button>
        </div>
      )}

      {(running || steps.length > 0) && (
        <section aria-label="Progress" className="no-print border-b border-rule py-8">
          <h2 className="text-[22px] font-semibold tracking-tight">Progress</h2>
          <ol className="mt-4 space-y-2">
            {steps.map((step, i) => (
              <li
                key={`${step.step ?? i}-${step.timestamp ?? i}`}
                className="grid grid-cols-[64px_minmax(0,1fr)] gap-x-4 text-[15px]"
              >
                <span className="text-ink-muted">{formatClock(step.timestamp)}</span>
                <span>{stepSentence(step)}</span>
              </li>
            ))}
          </ol>
          {running && (
            <p role="status" className="mt-4 text-[15px] text-ink-muted">
              {stalledStep
                ? `Still working on: ${stalledStep.charAt(0).toLowerCase()}${stalledStep.slice(1)}`
                : `${currentStep}. ${elapsed} seconds elapsed.`}
            </p>
          )}
        </section>
      )}

      {finished && (run.status === "failed" || run.status === "error") && (
        <div role="alert" className="py-8">
          <p className="text-[17px] font-medium">The check failed.</p>
          <p className="mt-1 max-w-[65ch] text-[15px] text-ink-muted">
            {run.error ?? "Something went wrong while running the check."}
          </p>
          <button
            type="button"
            onClick={() => void submit()}
            className="mt-3 text-[15px] underline decoration-rule underline-offset-4 hover:text-ink"
          >
            Try again
          </button>
        </div>
      )}

      {finished && run.status === "done" && run.answer && (
        <section aria-label="Memo" className="memo-print-area py-8">
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
    </div>
  );
}
