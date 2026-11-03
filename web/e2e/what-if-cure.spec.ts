import { expect, test } from "@playwright/test";

const panel = (page: import("@playwright/test").Page) =>
  page.getByRole("region", { name: "What-if" });

test("Set to cure applies the period's exact cure amount", async ({ page }) => {
  await page.goto("/app/company/SNBR?period=2026-04-04");
  const whatIf = panel(page);
  const slider = whatIf.getByRole("slider", { name: "Debt reduction" });
  await expect(slider).toHaveAttribute("step", "10000");
  await expect(whatIf.getByText("6.58x")).toBeVisible();

  await whatIf.getByRole("button", { name: "Set to cure" }).click();
  await expect(whatIf.getByText("$267,190,000")).toBeVisible();
  await expect(slider).toHaveValue("267190000");
  const leverage = whatIf.locator("div.card-float").first();
  await expect(leverage).toContainText("4.75x");
  await expect(leverage).toContainText("Pass");

  await slider.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(slider).toHaveValue("267180000");
  await expect(leverage).toContainText("Breach");

  await whatIf.getByRole("button", { name: "Reset" }).click();
  await expect(slider).toHaveValue("0");
});

// Sep 27 has no cure data; Jan 3 has cure data but passes.
for (const period of ["2025-09-27", "2026-01-03"]) {
  test(`no Set to cure button when ${period} has nothing to cure`, async ({
    page,
  }) => {
    await page.goto(`/app/company/SNBR?period=${period}`);
    const whatIf = panel(page);
    await expect(
      whatIf.getByRole("slider", { name: "Debt reduction" }),
    ).toBeVisible();
    await expect(
      whatIf.getByRole("button", { name: "Set to cure" }),
    ).toHaveCount(0);
  });
}

test("the agent page says which filings it reads", async ({ page }) => {
  await page.goto("/app/agent");
  await expect(
    page.getByText("Reads only filings available when the test was reported."),
  ).toBeVisible();
  await expect(
    page.getByText("Reads filings dated on or before the test date."),
  ).toHaveCount(0);
});
