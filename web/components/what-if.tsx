"use client";

import { useState, type ReactNode } from "react";
import { StatusMark } from "./site";
import {
  formatMoney,
  formatRatio,
  formatSignedRatio,
  type PeriodDetail,
} from "../lib/api";
import {
  computeWhatIf,
  cureDebtReduction,
  DEBT_REDUCTION_STEP,
  debtReductionMax,
  round2,
  type WhatIfBase,
} from "../lib/what-if";

function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
  children,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  children?: ReactNode;
}) {
  return (
    <div className="card-inset p-4">
      <div className="flex min-h-10 items-baseline justify-between gap-4">
        <label className="text-[15px] font-medium">{label}</label>
        <span className="index-label text-[13px]">{formatMoney(value)}</span>
      </div>
      <input
        type="range"
        aria-label={label}
        aria-valuetext={formatMoney(value)}
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="mt-2 w-full accent-[#15222C] dark:accent-[#E6ECE9]"
      />
      {children}
    </div>
  );
}

export function whatIfBase(detail: PeriodDetail): WhatIfBase {
  const savingsCap = Math.max(
    0,
    ...(detail.scenarios ?? detail.proforma_scenarios ?? []).map(
      (s) => s.savings,
    ),
  );
  return {
    total_debt: detail.numerator,
    ebitdar: detail.ebitdar,
    ebitda: detail.ebitda,
    interest_expense:
      detail.interest_coverage.denominator_value ?? detail.ebitda,
    net_leverage_limit: detail.net_leverage.threshold ?? 0,
    interest_coverage_limit: detail.interest_coverage.threshold ?? 0,
    savings_cap: savingsCap,
  };
}

export default function WhatIfPanel({ detail }: { detail: PeriodDetail }) {
  const base = whatIfBase(detail);
  const cureAmount = cureDebtReduction(detail.cure);
  const [debtReduction, setDebtReduction] = useState(0);
  const [ebitdaChange, setEbitdaChange] = useState(0);
  const [savings, setSavings] = useState(0);
  const result = computeWhatIf(base, {
    debt_reduction: debtReduction,
    ebitda_change: ebitdaChange,
    savings,
  });
  const reset = () => {
    setDebtReduction(0);
    setEbitdaChange(0);
    setSavings(0);
  };
  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-[75ch] text-[15px]">
          <span className="font-semibold">What-if.</span>{" "}
          <span className="text-ink-muted">
            Change the inputs to see the effect. This is not a covenant
            test.
          </span>
        </p>
        <button
          type="button"
          onClick={reset}
          className="btn btn-secondary btn-sm"
        >
          Reset
        </button>
      </div>
      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <Slider
          label="Debt reduction"
          value={debtReduction}
          min={0}
          max={debtReductionMax(cureAmount)}
          step={DEBT_REDUCTION_STEP}
          onChange={setDebtReduction}
        >
          {cureAmount !== null && (
            <button
              type="button"
              onClick={() => setDebtReduction(cureAmount)}
              className="btn btn-secondary btn-sm mt-3"
            >
              Set to cure
            </button>
          )}
        </Slider>
        <Slider
          label="EBITDA change"
          value={ebitdaChange}
          min={-50_000_000}
          max={150_000_000}
          step={500_000}
          onChange={setEbitdaChange}
        />
        <Slider
          label="Approved savings"
          value={savings}
          min={0}
          max={base.savings_cap}
          step={500_000}
          onChange={setSavings}
        />
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="card-float p-5">
          <p className="text-[36px] font-semibold leading-none tracking-tight">
            {formatRatio(round2(result.net_leverage))}
          </p>
          <p className="mt-2 text-[15px]">Net leverage</p>
          <p className="mt-1 text-[13px] text-ink-muted">
            Limit {formatRatio(base.net_leverage_limit)}. Headroom{" "}
            {formatSignedRatio(round2(result.net_leverage_headroom))}.{" "}
            <StatusMark
              tone={result.net_leverage_pass ? "pass" : "breach"}
              word={result.net_leverage_pass ? "Pass" : "Breach"}
            />
          </p>
        </div>
        <div className="card-float p-5">
          <p className="text-[36px] font-semibold leading-none tracking-tight">
            {formatRatio(round2(result.interest_coverage))}
          </p>
          <p className="mt-2 text-[15px]">Interest coverage</p>
          <p className="mt-1 text-[13px] text-ink-muted">
            Limit {formatRatio(base.interest_coverage_limit)}. Headroom{" "}
            {formatSignedRatio(round2(result.interest_coverage_headroom))}.{" "}
            <StatusMark
              tone={result.interest_coverage_pass ? "pass" : "breach"}
              word={result.interest_coverage_pass ? "Pass" : "Breach"}
            />
          </p>
          <p className="mt-1 text-[13px] text-ink-muted">
            Interest expense held constant.
          </p>
        </div>
      </div>
    </div>
  );
}
