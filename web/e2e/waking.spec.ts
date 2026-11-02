import { expect, test } from "@playwright/test";

test("a sleeping API shows the waking notice with a retry", async ({
  page,
}) => {
  await page.route("**://localhost:8001/**", (route) => route.abort());
  await page.goto("/");
  await expect(
    page.getByText("The data service is waking up."),
  ).toBeVisible();
  await expect(page.getByText("This can take up to a minute.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
});
