import type { AgentStep } from "./api";

const TOOL_DONE: Record<string, string> = {
  lookup_company: "Identified the company",
  find_agreements: "Found the governing agreement",
  extract_covenants: "Read the credit agreement",
  compute_covenants: "Computed covenants",
  project_next_test: "Projected the next test",
  cure_analysis: "Sized the cure",
  draft_memo: "Drafted the memo",
};


function prettyTool(tool: string | null): string {
  if (!tool) return "Working";
  return TOOL_DONE[tool] ?? tool.replace(/_/g, " ");
}

function cleanCompanyName(name: string): string {
  return name
    .replace(/,?\s+(Corp|Corporation|Inc|Inc\.|Co)\.?$/i, "")
    .trim();
}

function sentenceCaseTitle(title: string): string {
  const trimmed = title.trim();
  if (!trimmed) return trimmed;
  const letters = trimmed.replace(/[^A-Za-z]/g, "");
  if (letters && letters === letters.toUpperCase()) {
    const lower = trimmed.toLowerCase();
    return lower.charAt(0).toUpperCase() + lower.slice(1);
  }
  return trimmed;
}

function formatFiledDate(iso: string): string {
  const months = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  return `${months[Number(m[2]) - 1] || m[2]} ${Number(m[3])}, ${m[1]}`;
}

export function stepSentence(step: AgentStep): string {
  if (step.type === "run_start") return "Started the check.";
  if (step.type === "run_end") return "Finished the check.";
  if (step.type === "assistant_final") return "Finished the check.";
  const summary = (step.result_summary || "").trim();
  if (summary.startsWith("error:")) {
    return `That step failed: ${summary.slice("error:".length).trim()}.`;
  }
  if (step.tool === "lookup_company") {
    const m = /first (.+?) CIK (\d+)/.exec(summary);
    if (m) return `Found ${cleanCompanyName(m[1])} (SEC filer ${m[2]}).`;
    return "Found the company in SEC records.";
  }
  if (step.tool === "find_agreements") {
    const m = /^base: (\S+) \S+ (.+?); \d+ amendment/.exec(summary);
    if (m) {
      return `Found the governing agreement: ${sentenceCaseTitle(m[2])}, filed ${formatFiledDate(m[1])}.`;
    }
    if (summary.includes("no complete agreement")) {
      return "No complete governing agreement was found.";
    }
    return "Found the governing agreement.";
  }
  if (step.tool === "compute_covenants") {
    const m = /leverage ([\d.]+) vs ([\d.]+)/.exec(summary);
    if (m) {
      return `Computed covenants: net leverage ${Number(m[1]).toFixed(2)}x against ${Number(m[2]).toFixed(2)}x.`;
    }
    return "Computed covenants.";
  }
  if (step.tool === "project_next_test") {
    const m = /next test (\S+) \(threshold ([\d.]+)\): projected ([\d.]+)/.exec(summary);
    if (m) {
      return `Projected the next test on ${formatFiledDate(m[1])}: ${Number(m[3]).toFixed(2)}x against ${Number(m[2]).toFixed(2)}x.`;
    }
    return "Projected the next test.";
  }
  if (step.tool === "extract_covenants") {
    if (summary.includes("reviewed file used")) {
      return "Read the credit agreement from the reviewed extraction.";
    }
    return "Read the credit agreement.";
  }
  if (step.tool === "cure_analysis") return "Sized the cure.";
  if (step.tool === "draft_memo") {
    if (summary.includes("FLAGGED")) return "Drafted the memo, with figures flagged for checking.";
    if (summary.includes("verified")) return "Drafted the memo and verified its figures.";
    return "Drafted the memo.";
  }
  const label = step.tool ? prettyTool(step.tool) : "Working";
  return summary ? `${label}: ${summary}.` : `${label}.`;
}

