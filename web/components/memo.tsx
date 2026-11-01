"use client";

import Link from "next/link";
import { useState } from "react";

export interface FigureField {
  raw: string;
  field: string;
  value: number;
}

const MEMO_HEADINGS = [
  "Summary",
  "Covenant tests",
  "What drove it",
  "Cure",
  "Outlook",
  "Recommended actions",
];

function linkify(
  text: string,
  figureFields: FigureField[] | undefined,
  ticker: string,
  periodEnd: string,
  keyPrefix: string,
): React.ReactNode {
  if (!figureFields || figureFields.length === 0) return text;
  const queues = new Map<string, string[]>();
  for (const entry of figureFields) {
    const list = queues.get(entry.raw) ?? [];
    list.push(entry.field);
    queues.set(entry.raw, list);
  }
  const raws = [...queues.keys()].sort((a, b) => b.length - a.length);
  const nodes: React.ReactNode[] = [];
  let rest = text;
  let key = 0;
  while (rest.length > 0) {
    let bestIndex = -1;
    let bestRaw: string | null = null;
    for (const raw of raws) {
      const index = rest.indexOf(raw);
      if (index >= 0 && (bestIndex === -1 || index < bestIndex)) {
        bestIndex = index;
        bestRaw = raw;
      }
    }
    if (bestRaw === null || bestIndex < 0) {
      nodes.push(rest);
      break;
    }
    if (bestIndex > 0) nodes.push(rest.slice(0, bestIndex));
    const queue = queues.get(bestRaw) ?? [];
    const field = queue.length > 1 ? queue.shift() : queue[0];
    nodes.push(
      <Link
        key={`${keyPrefix}-${key++}`}
        href={`/app/company/${ticker}?period=${periodEnd}#fig-${field}`}
        className="underline decoration-rule underline-offset-4 hover:decoration-ink"
      >
        {bestRaw}
      </Link>,
    );
    rest = rest.slice(bestIndex + bestRaw.length);
  }
  return nodes;
}

export function MemoView({
  answer,
  figureFields,
  ticker = "SNBR",
  periodEnd = "2026-04-04",
}: {
  answer: string;
  figureFields?: FigureField[];
  ticker?: string;
  periodEnd?: string;
}) {
  const blocks: React.ReactNode[] = [];
  const lines = answer.split("\n");
  let i = 0;
  let key = 0;
  const isHeading = (line: string): string | null => {
    const cleaned = line
      .trim()
      .replace(/^#{1,6}\s*/, "")
      .replace(/^\*\*(.*)\*\*$/, "$1")
      .replace(/:$/, "")
      .trim();
    return (
      MEMO_HEADINGS.find((h) => h.toLowerCase() === cleaned.toLowerCase()) ??
      null
    );
  };
  const renderText = (text: string) =>
    linkify(text, figureFields, ticker, periodEnd, `k${key}`);
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    const heading = isHeading(line);
    if (heading) {
      blocks.push(
        <h3 key={key++} className="pt-2 text-[17px] font-semibold tracking-tight">
          {heading}
        </h3>,
      );
      i += 1;
      continue;
    }
    if (line.trim().startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const cells = lines[i]
          .trim()
          .replace(/^\||\|$/g, "")
          .split("|")
          .map((c) => c.trim());
        if (!cells.every((c) => /^:?-{3,}:?$/.test(c))) rows.push(cells);
        i += 1;
      }
      if (rows.length > 0) {
        const [head, ...body] = rows;
        blocks.push(
          <div key={key++} className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-[13px]">
              <thead>
                <tr className="border-b border-rule text-ink-muted">
                  {head.map((cell, ci) => (
                    <th key={ci} scope="col" className="py-2 pr-4 font-medium">
                      {cell}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {body.map((row, ri) => (
                  <tr key={ri} className="border-b border-rule last:border-0">
                    {row.map((cell, ci) => (
                      <td key={ci} className="py-2 pr-4">
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>,
        );
      }
      continue;
    }
    if (/^\s*[-*•]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*•]\s+/, "").trim());
        i += 1;
      }
      blocks.push(
        <ul key={key++} className="list-disc space-y-1 pl-5">
          {items.map((item, ii) => (
            <li key={ii}>{renderText(item)}</li>
          ))}
        </ul>,
      );
      continue;
    }
    const paragraph: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !isHeading(lines[i]) &&
      !lines[i].trim().startsWith("|") &&
      !/^\s*[-*•]\s+/.test(lines[i])
    ) {
      paragraph.push(lines[i].trim());
      i += 1;
    }
    blocks.push(<p key={key++}>{renderText(paragraph.join(" "))}</p>);
  }
  return (
    <div className="mt-4 max-w-[75ch] space-y-4 text-[15px] leading-relaxed">
      {blocks}
    </div>
  );
}

export function plainTextMemo(answer: string): string {
  const lines = answer.split("\n");
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim().startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const cells = lines[i]
          .trim()
          .replace(/^\||\|$/g, "")
          .split("|")
          .map((c) => c.trim());
        if (!cells.every((c) => /^:?-{3,}:?$/.test(c))) rows.push(cells);
        i += 1;
      }
      if (rows.length > 0) {
        const widths = rows[0].map((_, ci) =>
          Math.max(...rows.map((r) => (r[ci] ?? "").length)),
        );
        for (const row of rows) {
          out.push(
            row.map((cell, ci) => cell.padEnd(widths[ci])).join("  ").trimEnd(),
          );
        }
      }
      continue;
    }
    if (/^\s*[-*•]\s+/.test(line)) {
      out.push(`- ${line.replace(/^\s*[-*•]\s+/, "").trim()}`);
      i += 1;
      continue;
    }
    out.push(line.trim());
    i += 1;
  }
  return out.join("\n").replace(/\n{3,}/g, "\n\n").trim() + "\n";
}

export function MemoActions({
  answer,
  ticker = "SNBR",
  periodEnd = "2026-04-04",
  timestamp,
  asOf,
}: {
  answer: string;
  ticker?: string;
  periodEnd?: string;
  timestamp?: string | null;
  asOf?: string | null;
}) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(plainTextMemo(answer));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };
  const download = () => {
    const blob = new Blob([answer.trim() + "\n"], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `onya-memo-${ticker}-${periodEnd}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="memo-actions mt-6">
      <div className="print-only">
        <p className="text-[22px] font-medium">Onya</p>
        {timestamp ? <p>Run date: {timestamp.slice(0, 10)}</p> : null}
        {asOf ? <p>As of: {asOf}</p> : null}
        <p>
          Prepared by Onya from public SEC filings. Verify before relying on
          it.
        </p>
      </div>
      <div className="no-print flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void copy()}
          className="border border-ink px-4 py-2 text-[15px] font-medium"
        >
          Copy memo
        </button>
        <button
          type="button"
          onClick={download}
          className="border border-ink px-4 py-2 text-[15px] font-medium"
        >
          Download
        </button>
        <button
          type="button"
          onClick={() => window.print()}
          className="border border-ink px-4 py-2 text-[15px] font-medium"
        >
          Print
        </button>
        {copied ? (
          <span role="status" className="text-[15px]">
            Copied
          </span>
        ) : null}
      </div>
    </div>
  );
}
