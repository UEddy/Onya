import assert from "node:assert/strict";
import test from "node:test";

function makeStorage(initial?: Record<string, string>) {
  const store: Record<string, string> = { ...(initial ?? {}) };
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
  };
}

async function loadModule(storage: unknown) {
  // Each test sets its own window before importing; the module reads
  // the live global on every call, so no cleanup happens here.
  (globalThis as Record<string, unknown>).window = {
    localStorage: storage,
    addEventListener: () => {},
  };
  return await import("./watch.ts");
}

test("loads tickers from storage", async () => {
  const mod = await loadModule(makeStorage({ "onya-watchlist": '["SNBR"]' }));
  assert.deepEqual(mod.loadWatch(), ["SNBR"]);
});

test("empty and corrupt storage load empty", async () => {
  const mod = await loadModule(makeStorage());
  assert.deepEqual(mod.loadWatch(), []);
  const broken = await loadModule(makeStorage({ "onya-watchlist": "{" }));
  assert.deepEqual(broken.loadWatch(), []);
});

test("non-string entries are dropped", async () => {
  const mod = await loadModule(
    makeStorage({ "onya-watchlist": '["SNBR", 7, null]' }),
  );
  assert.deepEqual(mod.loadWatch(), ["SNBR"]);
});
