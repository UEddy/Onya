import { expect, test } from "@playwright/test";

test("private check runs the sample and shows the gap rows", async ({
  page,
}) => {
  await page.goto("/app/private");
  await expect(
    page.getByText(
      "Compare a borrower's compliance certificate with the public filings.",
    ),
  ).toBeVisible();
  await page.getByRole("button", { name: "Use the illustrative sample" }).click();
  await expect(page.getByText("ILLUSTRATIVE SAMPLE", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Run the comparison" }).click();
  await expect(page.getByText("Comparison: SNBR", { exact: false })).toBeVisible({
    timeout: 60000,
  });
  const table = page.getByRole("table");
  await expect(
    table.getByRole("columnheader", { name: "Certificate minus Onya" }),
  ).toBeVisible();
  await expect(table.getByRole("cell", { name: "5.06x" })).toBeVisible();
  await expect(table.getByRole("cell", { name: "6.58x" })).toBeVisible();
  await expect(table.getByRole("cell", { name: "1.70x" })).toBeVisible();
  await expect(table.getByRole("cell", { name: "0.84x" })).toBeVisible();
  await expect(table.getByRole("cell", { name: "-1.52x" })).toBeVisible();
  await expect(
    page.getByText("administrative agent approval", { exact: false }).first(),
  ).toBeVisible();
  await expect(
    page.getByText("is still above the 4.75x limit", { exact: false }).first(),
  ).toBeVisible();
  await expect(table.getByRole("cell", { name: "Verified" }).first()).toBeVisible();
});

