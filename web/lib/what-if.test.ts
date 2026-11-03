import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  computeWhatIf,
  cureDebtReduction,
  DEBT_REDUCTION_MAX,
  DEBT_REDUCTION_STEP,
  debtReductionMax,
  round2,
  type WhatIfBase,
} from "./what-if.ts";

const fixture = JSON.parse(
  readFileSync(new URL("./what-if.fixture.json", import.meta.url), "utf8"),
) as {
  base: WhatIfBase;
  cases: {
    name: string;
    inputs: { debt_reduction: number; ebitda_change: number; savings: number };
    expected: { net_leverage?: number; interest_coverage?: number };
  }[];
};

for (const entry of fixture.cases) {
  test(entry.name, () => {
    const result = computeWhatIf(fixture.base, entry.inputs);
    if (entry.expected.net_leverage !== undefined) {
      assert.equal(round2(result.net_leverage), entry.expected.net_leverage);
    }
    if (entry.expected.interest_coverage !== undefined) {
      assert.equal(
        round2(result.interest_coverage),
        entry.expected.interest_coverage,
      );
    }
  });
}

function cureWith(value: number) {
  return {
    base: {
      net_leverage: {
        figures: { debt_reduction_needed: { value } },
      },
    },
  };
}

test("cure amount comes from the period's cure data", () => {
  assert.equal(cureDebtReduction(cureWith(267_190_000)), 267_190_000);
  assert.equal(cureDebtReduction(cureWith(12_345_678)), 12_345_678);
});

test("no cure amount when the period has no debt reduction figure", () => {
  assert.equal(cureDebtReduction(null), null);
  assert.equal(cureDebtReduction(undefined), null);
  assert.equal(cureDebtReduction({ base: {} }), null);
  assert.equal(
    cureDebtReduction({
      base: { net_leverage: { figures: { debt_cushion: { value: 5 } } } },
    }),
    null,
  );
  assert.equal(cureDebtReduction(cureWith(0)), null);
});

test("the cure amount lands exactly on the limit and passes", () => {
  const cure = cureDebtReduction(cureWith(267_190_000));
  assert.notEqual(cure, null);
  const result = computeWhatIf(fixture.base, {
    debt_reduction: cure as number,
    ebitda_change: 0,
    savings: 0,
  });
  assert.equal(result.net_leverage, fixture.base.net_leverage_limit);
  assert.equal(result.net_leverage_pass, true);
  const short = computeWhatIf(fixture.base, {
    debt_reduction: (cure as number) - DEBT_REDUCTION_STEP,
    ebitda_change: 0,
    savings: 0,
  });
  assert.equal(short.net_leverage_pass, false);
});

test("the slider moves in $10,000 steps and reaches a large cure", () => {
  assert.equal(DEBT_REDUCTION_STEP, 10_000);
  assert.equal(debtReductionMax(null), DEBT_REDUCTION_MAX);
  assert.equal(debtReductionMax(267_190_000), DEBT_REDUCTION_MAX);
  assert.equal(debtReductionMax(500_000_000), 500_000_000);
});
