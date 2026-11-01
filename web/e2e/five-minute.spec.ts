import { expect, test, type Locator } from "@playwright/test";

test("five-minute path: landing, case, agent memo, linked figure", async ({
  page,
}) => {
  let clicks = 0;
  const click = async (locator: Locator) => {
    clicks += 1;
    await locator.click();
  };

  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /Your borrower passed. Barely./ }),
  ).toBeVisible();

  await click(
    page.getByRole("link", { name: "See the Sleep Number case" }).first(),
  );
  await expect(page.getByText("5.06x").first()).toBeVisible();
  await expect(page.getByText("6.58x").first()).toBeVisible();

  await click(page.getByRole("button", { name: /\$/ }).first());
  await expect(page.getByText("Evidence").first()).toBeVisible();

  await click(page.getByRole("link", { name: "Agent" }).first());
  await click(page.getByRole("button", { name: "Run the check" }));
  await expect(page.getByRole("heading", { name: "Memo" })).toBeVisible({
    timeout: 90_000,
  });
  await expect(
    page.getByText("Breach under every scenario").or(
      page.getByText("fails two covenants"),
    ).first(),
  ).toBeVisible();

  await click(page.getByRole("link", { name: "$962,096,000" }).first());
  await expect(page).toHaveURL(/period=2026-04-04/);
  await expect(page).toHaveURL(/#fig-total_debt/);
  await expect(page.locator("#fig-total_debt")).toBeVisible();
  await expect(
    page.locator("aside").getByText("$962,096,000"),
  ).toBeVisible();

  console.log(`CLICKS: ${clicks}`);
  expect(clicks).toBeLessThanOrEqual(8);
});
