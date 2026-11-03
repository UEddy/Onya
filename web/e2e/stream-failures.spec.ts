import { expect, test, type Page } from "@playwright/test";

const LOST = "The connection closed before the check finished.";
const STEP = JSON.stringify({
  step: 1,
  type: "tool_call",
  tool: "lookup_company",
  arguments: {},
  result_summary: "SNBR",
  total_tokens: 10,
});

function ndjson(...lines: string[]) {
  return {
    status: 200,
    contentType: "application/x-ndjson",
    body: lines.map((line) => `${line}\n`).join(""),
  };
}

async function runAgent(page: Page) {
  await page.goto("/app/agent");
  await page.getByRole("button", { name: "Run the check" }).click();
}

async function runPrivate(page: Page) {
  await page.goto("/app/private");
  await page.getByRole("button", { name: "Use the illustrative sample" }).click();
  await expect(page.locator("p", { hasText: "ILLUSTRATIVE SAMPLE" })).toBeVisible();
  await page.getByRole("button", { name: "Run the comparison" }).click();
}

test("agent: a stream closing with no final event shows an error", async ({ page }) => {
  await page.route("**/api/agent", (route) => route.fulfill(ndjson(STEP)));
  await runAgent(page);
  await expect(page.getByText(LOST, { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  await expect(page.getByRole("link", { name: "View a recorded run" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run the check" })).toBeEnabled();
});

test("agent: a reset connection shows the same error", async ({ page }) => {
  await page.route("**/api/agent", (route) => route.abort("connectionreset"));
  await runAgent(page);
  await expect(page.getByText(LOST, { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run the check" })).toBeEnabled();
});

test("agent: Try again runs the check again", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/agent", (route) => {
    calls += 1;
    if (calls === 1) return route.fulfill(ndjson(STEP));
    return route.fulfill(
      ndjson(
        JSON.stringify({ type: "run_result", reason: "done", answer: "Summary\nAll fine." }),
      ),
    );
  });
  await runAgent(page);
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("All fine.")).toBeVisible();
  await expect(page.getByText(LOST, { exact: false })).toHaveCount(0);
});

test("agent: heartbeats and a retry notice, then a server error", async ({ page }) => {
  await page.route("**/api/agent", (route) =>
    route.fulfill(
      ndjson(
        STEP,
        JSON.stringify({ type: "heartbeat", elapsed_s: 10 }),
        JSON.stringify({ type: "model_retry", attempt: 2, reason: "timeout" }),
        JSON.stringify({
          type: "error",
          code: "model_failed",
          error: "The model did not answer, so the check stopped.",
        }),
      ),
    ),
  );
  await runAgent(page);
  await expect(page.getByText("so the check stopped.")).toBeVisible();
  await expect(page.getByRole("link", { name: "View a recorded run" })).toBeVisible();
});

for (const [name, status, detail, text] of [
  ["hourly limit", 429, "rate limit: 5 runs per hour per IP", "five checks per hour"],
  ["daily budget", 429, "The daily token budget is used up for today.", "daily token budget"],
  ["paused", 503, "The live agent is paused.", "The live agent is paused."],
] as const) {
  test(`agent: ${name} offers the recorded run`, async ({ page }) => {
    await page.route("**/api/agent", (route) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify({ detail }) }),
    );
    await runAgent(page);
    await expect(page.getByText(text, { exact: false })).toBeVisible();
    await expect(page.getByRole("link", { name: "View a recorded run" })).toBeVisible();
  });
}

test("private: a stream closing with no final event shows an error", async ({ page }) => {
  await page.route("**/api/private", (route) =>
    route.request().method() === "POST"
      ? route.fulfill(ndjson(JSON.stringify({ type: "progress", step: "reading upload" })))
      : route.continue(),
  );
  await runPrivate(page);
  await expect(page.getByText(LOST, { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  await expect(page.getByRole("link", { name: "View a recorded run" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run the comparison" })).toBeEnabled();
});

test("private: a reset connection shows the same error", async ({ page }) => {
  await page.route("**/api/private", (route) =>
    route.request().method() === "POST" ? route.abort("connectionreset") : route.continue(),
  );
  await runPrivate(page);
  await expect(page.getByText(LOST, { exact: false })).toBeVisible();
});

test("private: an unavailable error says so", async ({ page }) => {
  await page.route("**/api/private", (route) =>
    route.request().method() === "POST"
      ? route.fulfill(
          ndjson(JSON.stringify({ type: "error", code: "unavailable", error: "off" })),
        )
      : route.continue(),
  );
  await runPrivate(page);
  await expect(page.getByText("Private mode is unavailable.")).toBeVisible();
});

async function draftRequest(page: Page) {
  await page.goto("/app/company/SNBR");
  await page.getByRole("button", { name: "Draft information request" }).click();
}

test("request panel: a stream closing with no final event shows an error", async ({ page }) => {
  await page.route("**/api/request", (route) => route.fulfill(ndjson(STEP)));
  await draftRequest(page);
  await expect(page.getByText(LOST, { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  await expect(page.getByText("Drafting the information request.")).toHaveCount(0);
});

test("request panel: a reset connection shows the same error", async ({ page }) => {
  await page.route("**/api/request", (route) => route.abort("connectionreset"));
  await draftRequest(page);
  await expect(page.getByText(LOST, { exact: false })).toBeVisible();
});

test("request panel: a server error event is shown as a failure", async ({ page }) => {
  await page.route("**/api/request", (route) =>
    route.fulfill(ndjson(JSON.stringify({ type: "error", error: "no" }))),
  );
  await draftRequest(page);
  await expect(page.getByText("The request could not be drafted.")).toBeVisible();
});

test("request panel: the rate limit says so", async ({ page }) => {
  await page.route("**/api/request", (route) =>
    route.fulfill({
      status: 429,
      contentType: "application/json",
      body: JSON.stringify({ detail: "rate limit: 5 runs per hour per IP" }),
    }),
  );
  await draftRequest(page);
  await expect(page.getByText("5 runs per hour per IP", { exact: false })).toBeVisible();
});

test("recorded run is labeled with its date and its figure links work", async ({ page }) => {
  await page.goto("/app/agent/recorded");
  await expect(page.getByRole("heading", { name: "Recorded run", level: 1 })).toBeVisible();
  await expect(page.getByText("Recorded run from Nov 1, 2026")).toBeVisible();
  await expect(page.getByText("Run 7c2a49625f4e. Not a live check.", { exact: false })).toBeVisible();
  const figure = page.locator('section[aria-label="Recorded run"] a[href*="#fig-"]').first();
  const href = await figure.getAttribute("href");
  expect(href).toContain("/app/company/SNBR?period=2026-04-04#fig-");
  await figure.click();
  await expect(page).toHaveURL(/\/app\/company\/SNBR\?period=2026-04-04#fig-/);
  const target = decodeURIComponent(href!.split("#")[1]);
  await expect(page.locator(`[id="${target}"]`)).toBeVisible({ timeout: 30_000 });
});
