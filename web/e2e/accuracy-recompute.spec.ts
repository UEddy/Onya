import { expect, test } from "@playwright/test";

test("accuracy page shows recomputed ratios labeled as they are", async ({
  page,
}) => {
  await page.goto("/accuracy");
  const panel = page.locator("#recompute");
  await expect(
    panel.getByRole("heading", { name: "Recomputed from filings" }),
  ).toBeVisible();
  await expect(
    panel.getByText(
      /12 ratios across 10 companies: 0 full matches, 12 partial, 0 mismatched\./,
    ),
  ).toBeVisible();

  const crs = panel.locator("tr", { hasText: "CRS" });
  await expect(crs).toContainText("0.60x");
  await expect(crs).toContainText("0.59x");
  await expect(crs).toContainText("Partial");

  const stgw = panel.locator("tr", { hasText: "STGW" });
  await expect(stgw).toContainText("Not computed");
  await expect(stgw).toContainText("N/A");
  await expect(stgw).toContainText("3.16x");
  await expect(stgw).not.toContainText("Not disclosed");
  await stgw.locator("summary").click();
  await expect(stgw).toContainText("ratio definition not extracted");

  await expect(panel).toContainText("OPTX was not recomputed");
  await expect(panel).not.toContainText("Full match");

  const terms = page.locator("#terms");
  await expect(terms.getByText(/21 terms across 11 companies: 19 matched/)).toBeVisible();
  await expect(terms).toContainText("OPTX status: agreement filed as scanned images");
});

for (const width of [1366, 360]) {
  test(`recompute section fits the page at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/accuracy");
    const panel = page.locator("#recompute");
    await panel.scrollIntoViewIfNeeded();
    await expect(panel.getByText(/12 ratios across 10 companies/)).toBeVisible();
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    const dir = process.env.ONYA_SHOT_DIR;
    if (dir) {
      // Panels reveal on scroll, so walk the page before the capture.
      const height = await page.evaluate(() => document.body.scrollHeight);
      for (let y = 0; y < height; y += 500) {
        await page.evaluate((top) => window.scrollTo(0, top), y);
        await page.waitForTimeout(120);
      }
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.waitForTimeout(800);
      await page.screenshot({
        path: `${dir}/accuracy-${width}.png`,
        fullPage: true,
      });
    }
  });
}
