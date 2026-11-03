import { expect, test } from "@playwright/test";

const panel = (page: import("@playwright/test").Page) =>
  page.getByRole("region", { name: "Rewind" });

for (const width of [360, 1440]) {
  test(`rewind reads and fits at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/app/company/SNBR#rewind");
    const rewind = panel(page);
    await expect(rewind.getByText("4.97x against 5.25x: pass.")).toBeVisible({ timeout: 30_000 });
    await expect(
      rewind.getByText("pass only with $50M of projected savings; 5.47x without."),
    ).toBeVisible();
    await expect(
      rewind.getByText("6.58x against 4.75x: breach; 5.06x with $44M of projected savings."),
    ).toBeVisible();
    await expect(rewind.getByText("As of Mar 12, 2026")).toBeVisible();
    await expect(rewind.getByText("Chapter 11 filing.")).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
}

test("a rewind step opens its test on the case page", async ({ page }) => {
  await page.goto("/app/company/SNBR");
  await panel(page).getByRole("link", { name: "Open this test" }).first().click();
  await expect(page).toHaveURL(/period=2025-09-27/);
  await expect(page.getByRole("tab", { selected: true })).toContainText("2025");
});

test("the landing page links to the rewind", async ({ page }) => {
  await page.goto("/");
  const link = page.getByRole("link", { name: /Rewind the case/ });
  await expect(link).toHaveAttribute("href", "/app/company/SNBR#rewind");
});
