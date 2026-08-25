import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("navigates views, searches, and resolves source details", async ({ page }) => {
  await page.goto("./");
  await expect(page.getByRole("link", { name: "Atlas home" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Story" })).toBeVisible();
  await page.getByRole("navigation", { name: "Graph views" }).getByRole("button", { name: /Optimization/ }).click();
  await expect(page.getByRole("heading", { name: "Optimization" })).toBeVisible();

  await page.getByRole("searchbox", { name: "Search evidence" }).fill("PagedAttention");
  const result = page.getByRole("button", { name: /PagedAttention/ }).first();
  await expect(result).toBeVisible();
  await result.click();
  await expect(page.getByRole("complementary", { name: "Evidence details" })).toBeVisible();
  await expect(page).toHaveURL(/node=atlas%3A%2F%2Fsource%2FSRC0002%40v1/);
});

test("has no automatically detectable serious accessibility violations", async ({ page }) => {
  await page.goto("./");
  await expect(page.getByRole("heading", { name: "Story" })).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((violation) => ["serious", "critical"].includes(violation.impact ?? ""))).toEqual([]);
});
