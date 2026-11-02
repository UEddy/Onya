import assert from "node:assert/strict";
import test from "node:test";
import { joinBackendUrl } from "./api.ts";

const BASE =
  "https://model-abc123.api.baseten.co/environments/production/sync";

test("read paths keep the sync prefix", () => {
  assert.equal(joinBackendUrl(BASE, ["health"]), `${BASE}/health`);
  assert.equal(joinBackendUrl(BASE, ["companies"]), `${BASE}/companies`);
});

test("agent paths keep the sync prefix", () => {
  assert.equal(
    joinBackendUrl(BASE, ["agent", "run"]),
    `${BASE}/agent/run`,
  );
  assert.equal(
    joinBackendUrl(BASE, ["agent", "run", "abc-123"]),
    `${BASE}/agent/run/abc-123`,
  );
});

test("a trailing slash on the base never doubles slashes", () => {
  assert.equal(joinBackendUrl(`${BASE}/`, ["health"]), `${BASE}/health`);
  assert.equal(
    joinBackendUrl(`${BASE}//`, ["agent", "run"]),
    `${BASE}/agent/run`,
  );
});

test("stray slashes on parts are trimmed, empties dropped", () => {
  assert.equal(joinBackendUrl(BASE, ["/health/"]), `${BASE}/health`);
  assert.equal(joinBackendUrl(BASE, ["", "backtest"]), `${BASE}/backtest`);
});
