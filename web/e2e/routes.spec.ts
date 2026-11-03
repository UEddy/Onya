import { expect, test, type Locator } from "@playwright/test";

test("get started lands on the app watchlist and the row opens the case", async ({
  page,
}) => {
  let clicks = 0;
  const click = async (locator: Locator) => {
    clicks += 1;
    await locator.click();
  };

  await page.goto("/");
  await click(page.getByRole("link", { name: "Get started" }).first());
  await expect(page).toHaveURL(/\/app\/watchlist/);
  await expect(page.getByText("Demo portfolio", { exact: true })).toBeVisible();

  await click(page.locator("tr", { hasText: "SNBR" }));
  await expect(page).toHaveURL(/\/app\/company\/SNBR/);
  await expect(page.getByText("Breach in both scenarios")).toBeVisible();

  console.log(`GET-STARTED CLICKS: ${clicks}`);
  expect(clicks).toBeLessThanOrEqual(8);
});

test("old case URL redirects to the app case with the row highlighted", async ({
  page,
}) => {
  await page.goto("/company/SNBR?period=2026-04-04#fig-total_debt");
  await expect(page).toHaveURL(
    /\/app\/company\/SNBR\?period=2026-04-04#fig-total_debt/,
  );
  await expect(page.locator("#fig-total_debt")).toHaveClass(
    /figure-highlight/,
  );
});

test("landing page states contract limits as 19 of 21, with the qualifier", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByText("19 of 21", { exact: true })).toBeVisible({
    timeout: 30_000,
  });
  await expect(
    page.getByText("contract limits matched; 2 changed by later amendments, flagged"),
  ).toBeVisible();
  const text = await page.locator("body").innerText();
  expect(text).not.toContain("19 of 19");
  expect(text).not.toContain("thresholds correct");
});
