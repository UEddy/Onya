import { expect, test } from "@playwright/test";

test("light theme holds on every route and through a memo link", async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/");
  await page.getByRole("button", { name: "Use light mode" }).click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);

  for (const path of [
    "/app/watchlist",
    "/app/company/SNBR",
    "/app/agent",
    "/app/accuracy",
    "/accuracy",
    "/",
  ]) {
    await page.goto(path);
    await expect(page.locator("html")).not.toHaveClass(/dark/);
  }

  await page.goto("/app/agent");
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await page.getByRole("button", { name: "Run the check" }).click();
  await expect(page.getByRole("heading", { name: "Memo" })).toBeVisible({
    timeout: 90_000,
  });
  await page.getByRole("link", { name: "$962,096,000" }).first().click();
  await expect(page).toHaveURL(/#fig-total_debt/);
  await expect(page.locator("html")).not.toHaveClass(/dark/);
});
