import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { computeWhatIf, round2, type WhatIfBase } from "./what-if.ts";

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
