import assert from "node:assert/strict";
import test from "node:test";
import { headroomBar } from "./headroom-bar.ts";

test("max covenant passing", () => {
  const bar = headroomBar(4.37, 5.0, "max", null);
  assert.equal(bar.breach, false);
  assert.equal(bar.applicableLimit, 5.0);
  assert.ok(Math.abs(bar.fillPct - (0.63 / 5.0) * 100) < 1e-9);
});

test("max covenant breaching", () => {
  const bar = headroomBar(6.58, 4.75, "max", null);
  assert.equal(bar.breach, true);
  assert.ok(Math.abs(bar.fillPct - (1.83 / 4.75) * 100) < 1e-9);
});

test("min covenant passing (GPK interest expense ratio)", () => {
  const bar = headroomBar(4.86, 3.0, "min", null);
  assert.equal(bar.breach, false);
  assert.ok(Math.abs(bar.fillPct - 62) < 1e-9);
});

test("min covenant breaching", () => {
  const bar = headroomBar(0.84, 2.1, "min", null);
  assert.equal(bar.breach, true);
});

test("waived limit applies (NUVR debt service coverage)", () => {
  const bar = headroomBar(1.99, 2.0, "min", 1.75);
  assert.equal(bar.breach, false);
  assert.equal(bar.applicableLimit, 1.75);
});

test("not disclosed (Syntec Optics)", () => {
  const bar = headroomBar(null, 4.75, "max", null);
  assert.equal(bar.breach, false);
  assert.equal(bar.fillPct, 0);
  assert.equal(bar.state, "not-disclosed");
});
