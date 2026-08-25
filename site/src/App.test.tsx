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

const view = {
  id: "bottleneck" as const,
  name: "Bottleneck",
  description: "Connect workload pressure to interventions.",
  node_ids: [node.id],
  edge_ids: [],
  default_layout: "cose",
  filters: {},
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
  indexes: { by_type: {}, by_status: {}, by_study: {}, by_tag: {}, referenced_by: {} },
  views: {
    story: { ...view, id: "story", name: "Story" },
    bottleneck: view,
    optimization: { ...view, id: "optimization", name: "Optimization" },
    evidence: { ...view, id: "evidence", name: "Evidence" },
    deployment: { ...view, id: "deployment", name: "Deployment" },
    all: { ...view, id: "all", name: "All" },
  },
};

const detail: EntityDetail = {
  node,
  artifact: { mechanism: "Paged allocation avoids contiguous reservation." },
  incoming: [],
  outgoing: [],
  referenced_by: [],
};

vi.mock("./data", () => ({
  loadAtlas: vi.fn(() => Promise.resolve(atlas)),
  loadEntity: vi.fn(() => Promise.resolve(detail)),
}));

vi.mock("./components/GraphCanvas", () => ({
  GraphCanvas: ({ onSelect }: { onSelect: (value: typeof node) => void }) => (
    <button onClick={() => onSelect(node)}>Select graph node</button>
  ),
}));

import { App } from "./App";

describe("Atlas explorer", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/llm-inference-optimization-atlas/");
  });

  it("switches graph views and opens entity evidence", async () => {
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Story" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Bottleneck/ }));
    expect(screen.getByRole("heading", { name: "Bottleneck" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Select graph node" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Paged KV cache" })).toBeVisible());
    expect(window.location.search).toContain("node=atlas%3A%2F%2Foptimization%2FOPT023%40v1");
  });

  it("offers keyboard-addressable search results", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Story" });
    fireEvent.change(screen.getByRole("searchbox", { name: "Search evidence" }), {
      target: { value: "paged" },
    });
    expect(screen.getByRole("button", { name: /Paged KV cache/ })).toBeInTheDocument();
  });
});
