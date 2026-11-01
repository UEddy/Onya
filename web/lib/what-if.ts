export interface WhatIfBase {
  total_debt: number;
  ebitdar: number;
  ebitda: number;
  interest_expense: number;
  net_leverage_limit: number;
  interest_coverage_limit: number;
  savings_cap: number;
}

export interface WhatIfInputs {
  debt_reduction: number;
  ebitda_change: number;
  savings: number;
}

export interface WhatIfResult {
  net_leverage: number;
  net_leverage_headroom: number;
  net_leverage_pass: boolean;
  interest_coverage: number;
  interest_coverage_headroom: number;
  interest_coverage_pass: boolean;
}

export function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

export function computeWhatIf(
  base: WhatIfBase,
  inputs: WhatIfInputs,
): WhatIfResult {
  const netLeverage =
    (base.total_debt - inputs.debt_reduction) /
    (base.ebitdar + inputs.ebitda_change + inputs.savings);
  const interestCoverage =
    (base.ebitda + inputs.ebitda_change + inputs.savings) /
    base.interest_expense;
  return {
    net_leverage: netLeverage,
    net_leverage_headroom: base.net_leverage_limit - netLeverage,
    net_leverage_pass: netLeverage <= base.net_leverage_limit,
    interest_coverage: interestCoverage,
    interest_coverage_headroom: interestCoverage - base.interest_coverage_limit,
    interest_coverage_pass: interestCoverage >= base.interest_coverage_limit,
  };
}
