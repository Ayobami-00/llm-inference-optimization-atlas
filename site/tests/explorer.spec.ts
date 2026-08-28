import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("navigates views, searches, and resolves source details", async ({ page }) => {
  await page.goto("./");
  await expect(page.getByRole("link", { name: "Atlas home" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Story" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Graph views" }).getByRole("button")).toHaveCount(5);
  await page.getByRole("searchbox", { name: "Search evidence" }).focus();
  await expect(page.getByText("Visible in Story")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Why this decision?" })).toHaveCount(0);
  await page.getByRole("navigation", { name: "Graph views" }).getByRole("button", { name: /Optimization/ }).click();
  await expect(page.getByRole("heading", { name: "Optimization", exact: true })).toBeVisible();

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

test("renders canonical references as named repository links", async ({ page }) => {
  await page.goto("./?view=story&node=atlas%3A%2F%2Fworkload%2FW001%40v1");
  const details = page.getByRole("complementary", { name: "Evidence details" });
  await expect(details).toBeVisible();
  const optimization = details.getByRole("link", {
    name: "Open Continuous batching in the repository",
  }).first();
  await expect(optimization).toHaveText("Continuous batching");
  await expect(optimization).toHaveAttribute(
    "href",
    /reference\/ontology\/v1\/optimizations\/0o2-admission-scheduling-and-batching\.yaml$/,
  );
  await expect(details).not.toContainText("atlas://");
});

test("presents a study as a guided story and groups replicate runs", async ({ page }) => {
  await page.goto("./studies/S003-cpu-enterprise-rag/v1/");
  await expect(page.getByRole("heading", { name: "Story" })).toBeVisible();
  await expect(page.getByLabel("Story view explanation").locator("p")).toHaveCount(3);
  await expect(page.getByLabel("Entity color key")).toContainText("WSWorkload");
  await expect(page.getByLabel("Graph reading order")).toContainText(
    "Workload→Study→Experiments→Comparisons→Findings→Decision",
  );
  await expect(page.getByRole("button", { name: "Why this decision?" })).toBeVisible();
  await expect(page.getByLabel("Relation legend")).toContainText("supports");

  const workload = page
    .getByRole("navigation", { name: "Graph node navigator" })
    .getByRole("button", { name: /WS003/ });
  await workload.click();
  const workloadDetails = page.getByRole("complementary", { name: "Evidence details" });
  const archetype = workloadDetails.getByRole("link", {
    name: "Open Enterprise RAG in the repository",
  });
  await expect(archetype).toHaveAttribute("href", /reference\/ontology\/v1\/workloads\.yaml$/);
  await page.getByRole("button", { name: "Close details" }).click();

  const experiment = page
    .getByRole("navigation", { name: "Graph node navigator" })
    .getByRole("button", { name: /E0009/ });
  await experiment.focus();
  await expect(page.getByRole("tooltip")).toContainText(
    "Select to open complete experiment details",
  );
  await page.keyboard.press("Enter");
  const details = page.getByRole("complementary", { name: "Evidence details" });
  await expect(details).toBeVisible();
  await expect(details.getByRole("heading", { name: "Experiment record" })).toBeVisible();
  await expect(details.getByText("Expected mechanism")).toBeVisible();
  await page.getByRole("button", { name: "Close details" }).click();

  await page
    .getByRole("navigation", { name: "Graph views" })
    .getByRole("button", { name: /Evidence/ })
    .click();
  await expect(page.getByLabel("Graph reading order")).toContainText("Replicate groups");
  await expect(page.getByLabel("Interactive evidence graph")).toHaveAttribute(
    "data-run-groups",
    "9",
  );
  await expect(page.getByLabel("Interactive evidence graph")).toHaveAttribute(
    "data-rendered-nodes",
    "27",
  );
});
