"use client";

import { useEffect, useState } from "react";
import {
  apiGet,
  ApiError,
  formatMoney,
  type SourceEvidence,
} from "../lib/api";

export function sourceKind(source: string): string {
  const kind = source.split(":")[0];
  if (kind === "contract") return "Contract";
  if (kind === "xbrl") return "XBRL";
  if (kind === "release") return "Release";
  if (kind === "estimate") return "Estimate";
  return "Source";
}

function tableName(table: string | null): string {
  if (table === "adjusted_ebitda_ttm") return "Adjusted EBITDA table";
  if (table === "leverage_table_ttm") return "Leverage table";
  return table ?? "Release table";
}

export function EvidencePanel({
  source,
  periodEnd,
}: {
  source: string;
  periodEnd: string;
}) {
  const [evidence, setEvidence] = useState<SourceEvidence | null>(null);
  const [failed, setFailed] = useState<"missing" | "error" | null>(null);

  useEffect(() => {
    if (source.startsWith("estimate:")) return;
    let cancelled = false;
    const request = apiGet<SourceEvidence>(
      `/source?ref=${encodeURIComponent(source)}&period_end=${encodeURIComponent(periodEnd)}`,
    );
    request.then(
      (data) => {
        if (!cancelled) setEvidence(data);
      },
      (error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 404) {
          setFailed("missing");
        } else {
          setFailed("error");
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [source, periodEnd]);

  if (source.startsWith("estimate:")) {
    const note = source.slice("estimate:".length).trim();
    return (
      <div>
        <p className="text-[13px] font-medium">Estimate</p>
        <p className="mt-1 text-[13px] text-ink-muted">
          Onya {note || "estimated this value"}. It is not tied to a filed
          figure, so there is no quote to show.
        </p>
      </div>
    );
  }

  if (failed === "missing") {
    return (
      <div>
        <p className="text-[13px] font-medium">No filed evidence</p>
        <p className="mt-1 text-[13px] text-ink-muted">
          Onya has no quote on file for this line. Treat the figure as
          unverified.
        </p>
      </div>
    );
  }

  if (failed === "error") {
    return (
      <div>
        <p className="text-[13px] font-medium">Evidence did not load</p>
        <p className="mt-1 text-[13px] text-ink-muted">
          Check that the data service is running, then select the row again.
        </p>
      </div>
    );
  }

  if (!evidence) {
    return (
      <p role="status" className="text-[13px] text-ink-muted">
        Finding the quote.
      </p>
    );
  }

  if (evidence.kind === "contract") {
    return (
      <div className="space-y-4">
        {evidence.cap?.quote && (
          <div>
            <p className="text-[13px] font-medium">Shared cap</p>
            <blockquote className="quote mt-2 border-l-2 border-rule pl-3 text-[15px]">
              {evidence.cap.quote}
            </blockquote>
          </div>
        )}
        {evidence.clauses.map((clause) => (
          <div key={clause.clause_ref}>
            <p className="text-[13px] font-medium">
              Clause {clause.clause_ref}
              {clause.section ? `, section ${clause.section}` : ""}
            </p>
            {clause.term && (
              <p className="mt-0.5 text-[13px] text-ink-muted">{clause.term}</p>
            )}
            {clause.label && (
              <p className="mt-0.5 text-[13px] text-ink-muted">{clause.label}</p>
            )}
            {clause.quote && (
              <blockquote className="quote mt-2 border-l-2 border-rule pl-3 text-[15px]">
                {clause.quote}
              </blockquote>
            )}
          </div>
        ))}
      </div>
    );
  }

  if (evidence.kind === "xbrl") {
    return (
      <div>
        <p className="font-mono text-[13px]">{evidence.concept}</p>
        {evidence.label && (
          <p className="mt-0.5 text-[13px] text-ink-muted">{evidence.label}</p>
        )}
        {evidence.value !== null && evidence.value !== undefined && (
          <p className="mt-2 text-[15px] font-medium">
            {formatMoney(evidence.value)}
          </p>
        )}
        <ul className="mt-3 space-y-2">
          {evidence.facts.slice(0, 4).map((fact, i) => (
            <li key={`${fact.filed}-${fact.end}-${i}`} className="text-[13px]">
              <span className="font-medium">{formatMoney(fact.val)}</span>{" "}
              <span className="text-ink-muted">
                {fact.form ?? "filing"}
                {fact.end ? ` for the period ended ${fact.end}` : ""}
                {fact.filed ? `, filed ${fact.filed}` : ""}
              </span>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {evidence.matches.slice(0, 3).map((match, i) => (
        <div key={`${match.period_end}-${match.table}-${i}`}>
          <p className="text-[13px] font-medium">
            {tableName(match.table)}
            {match.period_end ? `, quarter ended ${match.period_end}` : ""}
          </p>
          <p className="mt-0.5 text-[13px] text-ink-muted">{match.line}</p>
          {match.quote && (
            <blockquote className="quote mt-2 border-l-2 border-rule pl-3 text-[15px]">
              {match.quote}
              <span className="text-[13px] text-ink-muted"> thousand</span>
            </blockquote>
          )}
          {match.value_thousands !== null &&
            match.value_thousands !== undefined && (
              <p className="mt-1 text-[13px]">
                {formatMoney(match.value_thousands * 1000)}
              </p>
            )}
        </div>
      ))}
    </div>
  );
}
