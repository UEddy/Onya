"use client";

import { useCallback, useRef, useState } from "react";
import { DataNote, ErrorLine, LoadingLine, Panel } from "../../../components/site";
import { Reveal } from "../../../components/fade-up";
import type { PrivateComparison } from "../../../lib/api";

const MAX_UPLOAD_BYTES = 2_000_000;
const SAMPLE_WATERMARK =
  "ILLUSTRATIVE SAMPLE. Not a real compliance certificate.";

function formatValue(value: number | null): string {
  if (value === null || value === undefined) return "Not stated";
  return String(value);
}

function formatDiff(value: number | null): string {
  if (value === null || value === undefined) return "Not stated";
  return value > 0 ? `+${value}` : String(value);
}

function comparisonMarkdown(
  comparison: PrivateComparison,
  source: string,
): string {
  const lines = [
    `Private comparison: ${comparison.ticker}, ${comparison.period_end} test`,
    `Source: ${source}`,
    "",
    "| Covenant | Certificate | Onya | Difference | Evidence |",
    "| --- | --- | --- | --- | --- |",
  ];
  for (const row of comparison.rows) {
    lines.push(
      `| ${row.name} | ${formatValue(row.certificate)} | ${formatValue(row.onya)} | ${formatDiff(row.difference)} | ${row.verified ? "Verified" : "Unverified"} |`,
    );
  }
  if (comparison.flags.length > 0) {
    lines.push("", "Gaps:");
    for (const flag of comparison.flags) lines.push(`- ${flag}`);
  }
  if (comparison.summary.length > 0) {
    lines.push("", "Summary:");
    for (const line of comparison.summary) lines.push(`- ${line}`);
  }
  return lines.join("\n");
}

export default function PrivatePage() {
  const [ticker, setTicker] = useState("SNBR");
  const [periodEnd, setPeriodEnd] = useState("2026-04-04");
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [fileB64, setFileB64] = useState<string | null>(null);
  const [isSample, setIsSample] = useState(false);
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [comparison, setComparison] = useState<PrivateComparison | null>(
    null,
  );
  const [copied, setCopied] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const useSample = useCallback(async () => {
    setError(null);
    setUnavailable(false);
    try {
      const res = await fetch("/api/private", { cache: "no-store" });
      if (!res.ok) throw new Error("sample failed");
      const data = (await res.json()) as {
        text?: unknown;
        filename?: unknown;
      };
      if (typeof data.text !== "string") throw new Error("sample failed");
      setText(data.text);
      setFileName(null);
      setFileB64(null);
      setIsSample(true);
      setTicker("SNBR");
      setPeriodEnd("2026-04-04");
    } catch {
      setError("The sample could not be loaded. Please try again.");
    }
  }, []);

  const onFile = useCallback((file: File | undefined) => {
    setError(null);
    if (!file) return;
    if (file.size > MAX_UPLOAD_BYTES) {
      setError("The file is over 2 MB. Please use a smaller file.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        setError("The file could not be read. Please try again.");
        return;
      }
      const comma = result.indexOf(",");
      setFileB64(comma >= 0 ? result.slice(comma + 1) : result);
      setFileName(file.name);
      setText("");
      setIsSample(false);
    };
    reader.onerror = () => {
      setError("The file could not be read. Please try again.");
    };
    reader.readAsDataURL(file);
  }, []);

  const submit = useCallback(async () => {
    if (running) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setError(null);
    setUnavailable(false);
    setComparison(null);
    setCopied(false);
    setStatus("Reading the certificate");
    try {
      const res = await fetch("/api/private", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: ticker.trim(),
          period_end: periodEnd.trim(),
          text: text.trim() ? text : null,
          file_b64: fileB64,
          filename: fileName,
        }),
        cache: "no-store",
        signal: controller.signal,
      });
      if (res.status === 503) {
        setRunning(false);
        setStatus(null);
        setUnavailable(true);
        return;
      }
      if (!res.ok || !res.body) {
        const data = (await res.json().catch(() => ({
          detail: "",
        }))) as { detail?: string };
        setRunning(false);
        setStatus(null);
        setError(
          typeof data.detail === "string" && data.detail
            ? data.detail
            : "The comparison did not finish. Please try again.",
        );
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
          let record: {
            type?: unknown;
            step?: unknown;
            error?: unknown;
            comparison?: unknown;
          };
          try {
            record = JSON.parse(line) as typeof record;
          } catch {
            continue;
          }
          if (record.type === "progress" && typeof record.step === "string") {
            setStatus(
              record.step === "reading upload"
                ? "Reading the certificate"
                : "Extracting the reported figures",
            );
          } else if (record.type === "unavailable") {
            setRunning(false);
            setStatus(null);
            setUnavailable(true);
            return;
          } else if (record.type === "error") {
            setRunning(false);
            setStatus(null);
            setError(
              typeof record.error === "string" && record.error
                ? record.error
                : "The comparison did not finish. Please try again.",
            );
            return;
          } else if (
            record.type === "private_result" &&
            record.comparison &&
            typeof record.comparison === "object"
          ) {
            setComparison(record.comparison as PrivateComparison);
          }
        }
      }
      setRunning(false);
      setStatus(null);
    } catch {
      if (controller.signal.aborted) return;
      setRunning(false);
      setStatus(null);
      setError("The comparison did not finish. Please try again.");
    }
  }, [running, ticker, periodEnd, text, fileB64, fileName]);

  const sourceLabel = isSample
    ? "illustrative sample"
    : (fileName ?? "pasted text");

  const copy = useCallback(async () => {
    if (!comparison) return;
    try {
      await navigator.clipboard.writeText(
        comparisonMarkdown(comparison, sourceLabel),
      );
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }, [comparison, sourceLabel]);

  const download = useCallback(() => {
    if (!comparison) return;
    const blob = new Blob([comparisonMarkdown(comparison, sourceLabel)], {
      type: "text/markdown",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `private-comparison-${comparison.ticker}-${comparison.period_end}.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }, [comparison, sourceLabel]);

  const canRun =
    !running && ticker.trim().length > 0 && periodEnd.trim().length > 0 &&
    (text.trim().length > 0 || fileB64 !== null);

  return (
    <div className="space-y-5 pb-10 pt-6">
      <div className="enter">
        <p className="eyebrow">Private check</p>
        <h1 className="mt-2 text-[30px] font-semibold leading-tight tracking-tight sm:text-[36px]">
          Private mode
        </h1>
        <p className="mt-2 max-w-[75ch] text-[17px] text-ink-muted">
          Compare a borrower&apos;s compliance certificate with the public
          filings.
        </p>
        <p className="mt-3 inline-flex items-center gap-2 rounded-full border border-hairline bg-surface px-3 py-1 text-[12px] font-medium">
          <span aria-hidden="true" className="dot bg-pass" />
          Built with Muse Spark Open
        </p>
        <div className="mt-3">
          <DataNote />
        </div>
      </div>

      <Reveal>
        <Panel title="Certificate">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-[14px]">
              <span className="mb-1 block font-medium">Borrower ticker</span>
              <input
                value={ticker}
                onChange={(event) => setTicker(event.target.value)}
                className="w-full rounded-lg border border-hairline bg-surface px-3 py-2"
                autoComplete="off"
              />
            </label>
            <label className="block text-[14px]">
              <span className="mb-1 block font-medium">
                Test period end (YYYY-MM-DD)
              </span>
              <input
                value={periodEnd}
                onChange={(event) => setPeriodEnd(event.target.value)}
                className="w-full rounded-lg border border-hairline bg-surface px-3 py-2"
                autoComplete="off"
              />
            </label>
          </div>
          <div className="mt-4">
            <button
              type="button"
              onClick={useSample}
              className="btn btn-secondary"
            >
              Use the illustrative sample
            </button>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <label className="block text-[14px]">
              <span className="mb-1 block font-medium">
                Upload a PDF or .txt file (up to 2 MB)
              </span>
              <input
                ref={fileRef}
                type="file"
                accept=".pdf,.txt"
                onChange={(event) => onFile(event.target.files?.[0])}
                className="w-full text-[14px]"
              />
              {fileName && (
                <span className="mt-1 block text-[13px] text-ink-muted">
                  {fileName}
                </span>
              )}
            </label>
            <label className="block text-[14px]">
              <span className="mb-1 block font-medium">
                Or paste the certificate text
              </span>
              <textarea
                value={text}
                onChange={(event) => {
                  setText(event.target.value);
                  setFileName(null);
                  setFileB64(null);
                  if (fileRef.current) fileRef.current.value = "";
                  setIsSample(false);
                }}
                rows={8}
                className="w-full rounded-lg border border-hairline bg-surface px-3 py-2 font-mono text-[13px]"
                placeholder="Paste the compliance certificate here."
              />
            </label>
          </div>
          {isSample && (
            <p className="mt-3 rounded-lg border border-hairline bg-inset px-3 py-2 text-[13px] font-medium">
              {SAMPLE_WATERMARK} Built from public Sleep Number filings
              for demonstration.
            </p>
          )}
          <div className="mt-4">
            <button
              type="button"
              onClick={submit}
              disabled={!canRun}
              className="btn btn-primary"
            >
              {running ? "Comparing" : "Run the comparison"}
            </button>
          </div>
        </Panel>
      </Reveal>

      {unavailable && (
        <ErrorLine title="Private mode is unavailable.">
          The comparison model is not configured on this deployment.
        </ErrorLine>
      )}
      {error && !unavailable && (
        <ErrorLine title="The comparison did not finish." onRetry={submit}>
          {error}
        </ErrorLine>
      )}
      {running && <LoadingLine text={status ?? "Comparing the certificate."} />}

      {!running && comparison && (
        <Reveal>
          <Panel
            title={`Comparison: ${comparison.ticker}, ${comparison.period_end} test`}
          >
            <div className="overflow-x-auto">
              <table className="w-full text-[14px]">
                <thead>
                  <tr className="border-b border-hairline text-left text-ink-muted">
                    <th className="py-2 pr-4 font-medium">Covenant</th>
                    <th className="py-2 pr-4 text-right font-medium">Certificate</th>
                    <th className="py-2 pr-4 text-right font-medium">Onya</th>
                    <th className="py-2 pr-4 text-right font-medium">Difference</th>
                    <th className="py-2 font-medium">Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {comparison.rows.map((row) => (
                    <tr key={row.name} className="border-b border-hairline">
                      <td className="py-2 pr-4">{row.name}</td>
                      <td className="py-2 pr-4 text-right">
                        {formatValue(row.certificate)}
                      </td>
                      <td className="py-2 pr-4 text-right">
                        {formatValue(row.onya)}
                      </td>
                      <td className="py-2 pr-4 text-right">
                        {formatDiff(row.difference)}
                      </td>
                      <td className="py-2">
                        {row.verified ? "Verified" : "Unverified"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {comparison.flags.length > 0 && (
              <div className="mt-4">
                <p className="font-medium">Gaps</p>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-[14px]">
                  {comparison.flags.map((flag) => (
                    <li key={flag}>{flag}</li>
                  ))}
                </ul>
              </div>
            )}
            {comparison.summary.length > 0 && (
              <div className="mt-4">
                <p className="font-medium">Summary</p>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-[14px]">
                  {comparison.summary.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            )}
            <div className="mt-4 flex gap-2">
              <button type="button" onClick={copy} className="btn btn-secondary">
                {copied ? "Copied" : "Copy"}
              </button>
              <button
                type="button"
                onClick={download}
                className="btn btn-secondary"
              >
                Download
              </button>
            </div>
            <p className="mt-4 text-[13px] text-ink-muted">
              Processed in memory for this request and not stored by
              Onya. In this demo the model runs on Baseten. Because
              Muse Spark Open is open weights, a lender can run this
              step on infrastructure they control.
            </p>
          </Panel>
        </Reveal>
      )}
    </div>
  );
}
