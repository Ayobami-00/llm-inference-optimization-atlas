import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("atlas:s003-tour:v1", "seen"));
});

test("navigates views, searches, and resolves source details", async ({ page }) => {
  await page.goto("./");
  await expect(page.getByRole("link", { name: "Atlas home" })).toBeVisible();
  await expect(page.getByText("LLM Inference Optimization Atlas")).toBeVisible();
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

test("offers a first-visit tour through a real study", async ({ page }) => {
  await page.goto("./?welcome=1");
  const welcome = page.getByRole("dialog", { name: "Read one complete evidence story with us." });
  await expect(welcome).toBeVisible();
  await expect(welcome.getByLabel("Guided tour route")).toContainText(
    "WS003WorkloadE0009ExperimentCMP0013ComparisonF0013FindingDEC0003Decision",
  );
  await expect(welcome.getByRole("button", { name: "Start the S003 tour" })).toBeVisible();
  const results = await new AxeBuilder({ page }).include(".welcome-tour").analyze();
  expect(
    results.violations.filter((violation) => ["serious", "critical"].includes(violation.impact ?? "")),
  ).toEqual([]);
});

test("offers a branded and recoverable not-found page", async ({ page }) => {
  await page.goto("./404.html");
  await expect(page.getByText("LLM Inference Optimization Atlas")).toBeVisible();
  await expect(page.getByRole("heading", { name: "This path is not in the Atlas." })).toBeVisible();
  await expect(page.getByText("404 · This route has no evidence record")).toBeVisible();
  await expect(page.getByRole("link", { name: "Return to the Atlas" })).toHaveAttribute(
    "href",
    "/llm-inference-optimization-atlas/",
  );
  await expect(page.locator("#requested-path")).toContainText("404.html");
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.filter((violation) => ["serious", "critical"].includes(violation.impact ?? "")),
  ).toEqual([]);
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

test("preserves zoom and keeps the selected node beside the drawer", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.includes("mobile"), "The mobile drawer intentionally fills the viewport.");
  await page.goto("./studies/S003-cpu-enterprise-rag/v1/");
  const canvas = page.getByLabel("Interactive evidence graph");
  await expect(canvas).toHaveAttribute("data-zoom", /\d/);
  await page.getByRole("button", { name: "Zoom in" }).click();
  await page.getByRole("button", { name: "Zoom in" }).click();
  const zoomed = Number(await canvas.getAttribute("data-zoom"));

  const decision = page
    .getByRole("navigation", { name: "Graph node navigator" })
    .getByRole("button", { name: /DEC0003/ });
  await decision.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("complementary", { name: "Evidence details" })).toBeVisible();

  await expect.poll(async () => Number(await canvas.getAttribute("data-zoom"))).toBeCloseTo(zoomed, 3);
  await expect(canvas).toHaveAttribute("data-selected-node-visible", "true");
});

test("highlights the supporting path from a decision drawer", async ({ page }) => {
  await page.goto("./studies/S003-cpu-enterprise-rag/v1/");
  const decision = page
    .getByRole("navigation", { name: "Graph node navigator" })
    .getByRole("button", { name: /DEC0003/ });
  await decision.focus();
  await page.keyboard.press("Enter");

  const details = page.getByRole("complementary", { name: "Evidence details" });
  const why = details.getByRole("button", { name: "Why this decision?" });
  await why.click();
  await expect(
    details.getByRole("button", { name: "Decision path highlighted" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(details.getByText(/Supporting findings and the selected configuration/)).toBeVisible();
  await expect
    .poll(async () => Number(await page.getByLabel("Interactive evidence graph").getAttribute("data-highlighted-elements")))
    .toBeGreaterThan(1);
  await expect
    .poll(async () => Number(await page.getByLabel("Interactive evidence graph").getAttribute("data-dimmed-elements")))
    .toBeGreaterThan(1);
});

test("spotlights a selected node and its immediate relationships", async ({ page }) => {
  await page.goto("./studies/S003-cpu-enterprise-rag/v1/");
  const canvas = page.getByLabel("Interactive evidence graph");
  const experiment = page
    .getByRole("navigation", { name: "Graph node navigator" })
    .getByRole("button", { name: /E0009/ });
  await experiment.focus();
  await page.keyboard.press("Enter");
  await expect(canvas).toHaveAttribute("data-selected-id", /E0009/);
  await expect.poll(async () => Number(await canvas.getAttribute("data-dimmed-elements"))).toBeGreaterThan(1);
  await expect(page.getByText(/Dark rings show the selected record/)).toBeVisible();
});

test("explains graph relationships through arrow focus", async ({ page }) => {
  await page.goto("./studies/S003-cpu-enterprise-rag/v1/");
  const relationship = page
    .getByRole("navigation", { name: "Graph relationship navigator" })
    .getByRole("button")
    .first();
  await relationship.focus();
  const tooltip = page.getByRole("tooltip");
  await expect(tooltip).toBeVisible();
  await expect(tooltip.locator("p")).not.toBeEmpty();
  await expect(tooltip).toContainText(/confidence/);
  const bounds = await tooltip.boundingBox();
  const viewport = page.viewportSize();
  expect(bounds).not.toBeNull();
  expect(viewport).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport!.width);
});

test("walks through S003 and finishes by revealing the decision path", async ({ page }) => {
  await page.goto("./studies/S003-cpu-enterprise-rag/v1/?view=story&tour=1");
  const tour = page.getByRole("complementary", { name: "S003 guided tour" });
  const canvas = page.getByLabel("Interactive evidence graph");
  await expect(tour).toContainText("Step 1 of 5");
  await expect(canvas).toHaveAttribute("data-selected-id", /WS003/);
  await expect(canvas).toHaveAttribute("data-tour-node-visible", "true");

  for (const code of ["E0009", "CMP0013", "F0013", "DEC0003"]) {
    await tour.getByRole("button", { name: "Next evidence step" }).click();
    await expect(canvas).toHaveAttribute("data-selected-id", new RegExp(code));
    await expect(canvas).toHaveAttribute("data-tour-node-visible", "true");
  }

  await tour.getByRole("button", { name: "Reveal why this decision" }).click();
  await expect(tour).not.toBeVisible();
  await expect(page.getByRole("complementary", { name: "Evidence details" })).toBeVisible();
  await expect.poll(async () => Number(await canvas.getAttribute("data-highlighted-elements"))).toBeGreaterThan(1);
  await expect.poll(async () => Number(await canvas.getAttribute("data-dimmed-elements"))).toBeGreaterThan(1);
});

test("presents a guided study story and expands replicate runs", async ({ page }) => {
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
  await workload.focus();
  await page.keyboard.press("Enter");
  const workloadDetails = page.getByRole("complementary", { name: "Evidence details" });
  const archetype = workloadDetails.getByRole("link", {
    name: "Open Enterprise RAG in the repository",
  }).first();
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
  await expect(page.getByLabel("Graph reading order")).toContainText("Runs");
  await expect(page.getByLabel("Interactive evidence graph")).toHaveAttribute(
    "data-run-groups",
    "0",
  );
  await expect(page.getByLabel("Interactive evidence graph")).toHaveAttribute(
    "data-rendered-nodes",
    "45",
  );
});
