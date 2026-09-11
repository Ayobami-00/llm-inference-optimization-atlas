import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AtlasData, EntityDetail } from "./types";

const node = {
  id: "atlas://optimization/OPT023@v1",
  type: "optimization" as const,
  label: "Paged KV cache",
  status: "active",
  source_path: "reference/ontology/v1/optimizations/kv.yaml",
  artifact_ref: "atlas://optimization/OPT023@v1",
  summary: "Manage non-contiguous KV blocks.",
  tags: ["O4"],
  detail_path: "entities/OPT023@v1.json",
};

const referencedNode = {
  ...node,
  id: "atlas://optimization/OPT007@v1",
  label: "Continuous batching",
  source_path: "reference/ontology/v1/optimizations/scheduling.yaml",
  artifact_ref: "atlas://optimization/OPT007@v1",
  summary: "Continuously fill available batch slots.",
  detail_path: "entities/OPT007@v1.json",
};

const view = {
  id: "bottleneck" as const,
  name: "Bottleneck",
  description: "Connect workload pressure to interventions.",
  node_ids: [node.id],
  edge_ids: [],
  default_layout: "cose",
  filters: {},
};

const storyView = {
  ...view,
  id: "story" as const,
  name: "Story",
  description: "Follow the evaluated workload from study design to deployment decision.",
  filters: {
    presentation: {
      stages: [
        { label: "Workload", types: ["workload" as const] },
        { label: "Decision", types: ["decision" as const] },
      ],
      intro: "Read the columns from workload to decision.",
      relations: ["PRODUCES", "JUSTIFIES"],
    },
  },
};

const atlas: AtlasData = {
  root: "/data",
  manifest: {
    graph_version: 1,
    generated_at: "2026-08-25T00:00:00Z",
    repository_commit: "0123456789abcdef",
    scope: { type: "global" },
    counts: { nodes: 1, edges: 0, entities: 1 },
    files: { graph: "graph.json", indexes: "indexes.json", views: [] },
  },
  graph: { graph_version: 1, nodes: [node], edges: [] },
  referenceNodes: [node, referencedNode],
  indexes: { by_type: {}, by_status: {}, by_study: {}, by_tag: {}, referenced_by: {} },
  views: {
    story: storyView,
    bottleneck: view,
    optimization: { ...view, id: "optimization", name: "Optimization" },
    evidence: { ...view, id: "evidence", name: "Evidence" },
    deployment: { ...view, id: "deployment", name: "Deployment" },
    all: { ...view, id: "all", name: "All" },
  },
};

const detail: EntityDetail = {
  node,
  artifact: {
    mechanism: "Paged allocation avoids contiguous reservation.",
    candidate_optimizations: [referencedNode.artifact_ref, "atlas://optimization/OPT999@v1"],
    contrast: {
      id: "host-sync-vs-prefetch",
      baseline: "atlas://configuration/CFG022@v1",
      candidate: "atlas://configuration/CFG023@v1",
    },
    method: {
      paired: true,
      inference: "descriptive_only",
      independent_units: 1,
    },
    effects: [
      {
        metric: "atlas://metric/MET012@v1",
        baseline: 0,
        candidate: 5144.17,
        absolute: 5144.17,
        relative: null,
        confidence_interval: { lower: 4500, upper: 5600, level: 0.95 },
        unit: "ms",
      },
      {
        metric: "atlas://metric/MET019@v1",
        baseline: 90,
        candidate: 100,
        absolute: 10,
        relative: 0.1111,
        confidence_interval: { lower: 4, upper: 16, level: 0.95 },
        unit: "token/s",
        scope: { content_family: "code", context_tokens: 32768, concurrency: 8 },
      },
      {
        metric: "atlas://metric/MET019@v1",
        baseline: 120,
        candidate: 126,
        absolute: 6,
        relative: 0.05,
        confidence_interval: { lower: 1, upper: 11, level: 0.95 },
        unit: "token/s",
        scope: { content_family: "code", context_tokens: 8192, concurrency: 8 },
      },
      {
        metric: "atlas://metric/MET019@v1",
        baseline: 150,
        candidate: 147,
        absolute: -3,
        relative: -0.02,
        confidence_interval: { lower: -8, upper: 2, level: 0.95 },
        unit: "token/s",
        scope: { content_family: "code", context_tokens: 8192, concurrency: 16 },
      },
      {
        metric: "atlas://metric/MET019@v1",
        baseline: 80,
        candidate: 96,
        absolute: 16,
        relative: 0.2,
        confidence_interval: { lower: 8, upper: 24, level: 0.95 },
        unit: "token/s",
        scope: { content_family: "natural", context_tokens: 32768, concurrency: 16 },
      },
      {
        metric: "atlas://metric/MET013@v1",
        baseline: 100,
        candidate: 80,
        absolute: -20,
        relative: -0.2,
        confidence_interval: { lower: -25, upper: -15, level: 0.95 },
        unit: "ms/token",
        scope: { content_family: "code", context_tokens: 32768, concurrency: 8 },
      },
    ],
  },
  incoming: [],
  outgoing: [],
  referenced_by: [],
};

const centerGraph = vi.fn();
const graphCore = {
  container: () => null,
  elements: () => ({ unselect: vi.fn() }),
  getElementById: () => ({ length: 1, select: vi.fn() }),
  center: centerGraph,
};

vi.mock("./data", () => ({
  loadAtlas: vi.fn(() => Promise.resolve(atlas)),
  loadEntity: vi.fn(() => Promise.resolve(detail)),
}));

vi.mock("./components/GraphCanvas", () => ({
  GraphCanvas: ({
    onSelect,
    onReady,
  }: {
    onSelect: (value: typeof node) => void;
    onReady: (value: typeof graphCore) => void;
  }) => (
    <button
      onClick={() => {
        onReady(graphCore);
        onSelect(node);
      }}
    >
      Select graph node
    </button>
  ),
}));

import { App } from "./App";

describe("Atlas explorer", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/llm-inference-optimization-atlas/");
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: vi.fn(() => "seen"),
        setItem: vi.fn(),
      },
    });
    centerGraph.mockClear();
  });

  it("switches graph views and opens entity evidence", async () => {
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Story" })).toBeInTheDocument();
    expect(screen.getByText("LLM Inference Optimization Atlas")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /All/ })).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Follow the evaluated workload from study design to deployment decision.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("generic", { name: "Graph reading order" })).toHaveTextContent(
      "StartWorkload→Decision",
    );
    expect(screen.getByRole("generic", { name: "Relation legend" })).toHaveTextContent(
      "produces",
    );
    const explanation = screen.getByRole("generic", { name: "Story view explanation" });
    expect(explanation.querySelectorAll("p")).toHaveLength(3);
    expect(explanation).toHaveTextContent("concrete workload and study");
    expect(screen.getByRole("generic", { name: "Entity color key" })).toHaveTextContent(
      "OPTOptimization",
    );
    fireEvent.click(screen.getByRole("button", { name: /Bottleneck/ }));
    expect(screen.getByRole("heading", { name: "Bottleneck" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Select graph node" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Paged KV cache" })).toBeVisible());
    expect(screen.getByRole("heading", { name: "Optimization record" })).toBeVisible();
    expect(screen.getByText("Paged allocation avoids contiguous reservation.")).toBeVisible();
    expect(screen.getByText("Relative effect unavailable")).toBeVisible();
    expect(screen.getByLabelText("Comparison contrast")).toHaveTextContent(
      "Host Sync Vs PrefetchCFG022 → CFG023",
    );
    expect(screen.getByRole("note", { name: "Descriptive comparison limitation" })).toHaveTextContent(
      "1 independent paired block",
    );
    expect(screen.getByRole("note", { name: "Descriptive comparison limitation" })).toHaveTextContent(
      "confidence intervals and deployment claims are unavailable",
    );
    fireEvent.change(screen.getByLabelText("Metric"), {
      target: { value: "atlas://metric/MET019@v1" },
    });
    expect(screen.getByRole("table", { name: "Scoped measured effects" })).toBeVisible();
    expect(
      screen.getByText("Output token throughput (MET019) effects by exact workload scope"),
    ).toBeVisible();
    expect(screen.getByLabelText("Content Family")).toBeVisible();
    expect(screen.getByLabelText("Signed-change color key")).toHaveTextContent(
      "does not by itself mean improvement or regression",
    );
    expect(
      screen.getByRole("table", {
        name: "Output token throughput (MET019) context by concurrency heatmap, Content Family: Code",
      }),
    ).toBeVisible();
    expect(screen.getAllByText("+11.1%").length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText("Metric"), {
      target: { value: "atlas://metric/MET013@v1" },
    });
    expect(screen.getByText("Time per output token (MET013) effects by exact workload scope")).toBeVisible();
    const lowerCells = screen.getAllByText("-20.0%");
    expect(lowerCells.length).toBeGreaterThan(0);
    lowerCells.forEach((cell) => {
      expect(cell).toHaveAttribute("title", expect.stringContaining("Candidate 20.0% lower"));
      expect(cell).toHaveStyle({ backgroundColor: "rgba(50, 126, 160, 0.52)" });
    });
    const recordLink = screen.getByRole("link", {
      name: "Open Continuous batching in the repository",
    });
    expect(recordLink).toHaveTextContent("Continuous batching");
    expect(recordLink).toHaveAttribute(
      "href",
      "https://github.com/Ayobami-00/llm-inference-optimization-atlas/blob/0123456789abcdef/reference/ontology/v1/optimizations/scheduling.yaml",
    );
    expect(screen.queryByText(referencedNode.artifact_ref)).not.toBeInTheDocument();
    expect(
      screen.getByTitle("Unresolved Atlas reference: atlas://optimization/OPT999@v1"),
    ).toHaveTextContent("OPT999");
    expect(centerGraph).not.toHaveBeenCalled();
    expect(window.location.search).toContain("node=atlas%3A%2F%2Foptimization%2FOPT023%40v1");
  });

  it("offers visible nodes before filtering keyboard-addressable search results", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Story" });
    const search = screen.getByRole("searchbox", { name: "Search evidence" });
    fireEvent.focus(search);
    expect(screen.getByText("Visible in Story")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /OPT023.*Paged KV cache/ })).toBeInTheDocument();
    fireEvent.change(search, {
      target: { value: "paged" },
    });
    expect(screen.getByRole("button", { name: /Paged KV cache/ })).toBeInTheDocument();
  });

  it("offers the study walkthrough from the global homepage", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Story" });

    fireEvent.click(screen.getByRole("button", { name: /Watch walkthrough/ }));
    expect(
      screen.getByRole("dialog", { name: "Read one complete evidence story with us." }),
    ).toBeVisible();
    const recording = screen.getByLabelText("S003 guided study walkthrough");
    expect(recording.tagName).toBe("VIDEO");
    expect(recording.querySelector("source")?.getAttribute("src")).toMatch(
      /\/media\/s003-guided-tour\.mp4$/,
    );
    expect(screen.getByText(/walkthrough of WS003/)).toBeVisible();
  });
});
