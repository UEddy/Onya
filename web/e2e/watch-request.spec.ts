import { expect, test } from "@playwright/test";

test("watching SNBR shows the sidebar count and the next test", async ({
  page,
}) => {
  await page.goto("/app/watchlist");
  await expect(
    page.getByText("Demo portfolio", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Watch SNBR" }).click();
  await expect(
    page.getByRole("button", { name: "Stop watching SNBR" }),
  ).toBeVisible();
  await expect(page.getByText("Watching 1")).toBeVisible();
  await expect(page.getByText(/Jul 4, 2026/)).toBeVisible();
});

test("the case page drafts the information request", async ({ page }) => {
  await page.goto("/app/company/SNBR");
  await page.getByRole("button", { name: "Draft information request" }).click();
  await expect(
    page.getByText("Information request: Sleep Number covenants"),
  ).toBeVisible({ timeout: 60_000 });
  await expect(
    page.getByText("Draft. Review before sending."),
  ).toBeVisible();
});

test("filed-since lists newer filings with SEC links", async ({ page }) => {
  await page.goto("/app/company/SNBR?period=2026-04-04");
  await expect(page.getByText("Filed since this check")).toBeVisible();
  const link = page.getByRole("link", { name: /8-K, filed/ }).first();
  await expect(link).toBeVisible();
  const href = await link.getAttribute("href");
  expect(href ?? "").toContain("https://www.sec.gov/Archives/edgar/data/");
  await expect(
    page.getByText("Filings checked through Oct 30, 2026"),
  ).toBeVisible();
});
