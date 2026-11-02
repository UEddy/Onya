"use client";

import { useState } from "react";
import { linkify } from "./memo";

/* Borrower information request: deterministic letter from computed
   results, rendered with figure links to the case page. Draft only:
   nothing is sent anywhere. */

export function RequestView({
  request,
  figureFields,
  ticker,
  periodEnd,
}: {
  request: string;
  figureFields?: { raw: string; field: string; value: number }[];
  ticker: string;
  periodEnd: string;
}) {
  const paragraphs = request.split(/\n{2,}|\n(?=\d+\. )/);
  return (
    <div>
      {paragraphs.map((paragraph, index) => (
        <p
          key={index}
          className="mt-3 max-w-[75ch] whitespace-pre-line text-[15px] first:mt-0"
        >
          {linkify(paragraph, figureFields, ticker, periodEnd, `r${index}`)}
        </p>
      ))}
    </div>
  );
}

export function RequestActions({
  request,
  ticker,
  periodEnd,
}: {
  request: string;
  ticker: string;
  periodEnd: string;
}) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(request);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* Clipboard unavailable: the text stays visible to copy by hand. */
    }
  };
  const download = () => {
    const blob = new Blob([request], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `onya-information-request-${ticker}-${periodEnd}.md`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="no-print mt-4 flex flex-wrap gap-2">
      <button
        type="button"
        onClick={() => void copy()}
        className="btn btn-secondary btn-sm"
      >
        {copied ? "Copied" : "Copy request"}
      </button>
      <button
        type="button"
        onClick={download}
        className="btn btn-secondary btn-sm"
      >
        Download
      </button>
      <button
        type="button"
        onClick={() => window.print()}
        className="btn btn-secondary btn-sm"
      >
        Print
      </button>
    </div>
  );
}
