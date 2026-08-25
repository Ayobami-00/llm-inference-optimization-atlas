import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import { useEffect, useMemo, useRef } from "react";

import type { GraphData, GraphNode, GraphView } from "../types";

const colors: Record<string, string> = {
  workload_archetype: "#e8b35a",
  study: "#f4e8c8",
  workload: "#d99a45",
  characteristic: "#89a88f",
  traffic: "#74a3a2",
  quality_contract: "#a7c17e",
  slo: "#7eb4b8",
  model: "#b39ad6",
  hardware: "#8da7cf",
  runtime: "#6fb5a4",
  configuration: "#dad1b5",
  bottleneck: "#dc715e",
  optimization: "#59b894",
  hypothesis: "#d4a66e",
  experiment: "#e0c56e",
  run: "#91b7a2",
  comparison: "#cb9f73",
  finding: "#f0d985",
  decision: "#f4efe0",
  replication: "#acbf8f",
  source: "#77827d",
};

interface Props {
  graph: GraphData;
  view: GraphView;
  query: string;
  selectedTypes: Set<string>;
  showNegative: boolean;
  highlighted: Set<string>;
  onSelect: (node: GraphNode) => void;
  onReady: (core: Core) => void;
}

export function GraphCanvas({
  graph,
  view,
  query,
  selectedTypes,
  showNegative,
  highlighted,
  onSelect,
  onReady,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const core = useRef<Core | null>(null);
  const viewNodes = useMemo(() => new Set(view.node_ids), [view]);
  const viewEdges = useMemo(() => new Set(view.edge_ids), [view]);

  const elements = useMemo<ElementDefinition[]>(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const visibleNodes = graph.nodes.filter((node) => {
      const isNegative = node.tags.some((tag) =>
        ["degradation", "no_significant_effect", "inconclusive", "contradicted"].includes(tag),
      );
      return (
        viewNodes.has(node.id) &&
        (selectedTypes.size === 0 || selectedTypes.has(node.type)) &&
        (showNegative || !isNegative) &&
        (!normalizedQuery ||
          `${node.label} ${node.summary} ${node.tags.join(" ")}`
            .toLowerCase()
            .includes(normalizedQuery))
      );
    });
    const nodeIds = new Set(visibleNodes.map((node) => node.id));
    const nodeElements: ElementDefinition[] = visibleNodes.map((node) => ({
      data: { ...node, color: colors[node.type] ?? "#c8d0c8" },
      classes: highlighted.has(node.id) ? "path" : "",
    }));
    const edgeElements: ElementDefinition[] = graph.edges
      .filter(
        (edge) =>
          viewEdges.has(edge.id) && nodeIds.has(edge.source) && nodeIds.has(edge.target),
      )
      .map((edge) => ({
        data: edge,
        classes:
          highlighted.has(edge.id) ||
          (highlighted.has(edge.source) && highlighted.has(edge.target))
            ? "path"
            : "",
      }));
    return [...nodeElements, ...edgeElements];
  }, [graph, highlighted, query, selectedTypes, showNegative, viewEdges, viewNodes]);

  useEffect(() => {
    if (!container.current) return;
    const cy = cytoscape({
      container: container.current,
      elements,
      minZoom: 0.15,
      maxZoom: 2.5,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)",
            "border-color": "#09110f",
            "border-width": 2,
            color: "#ece9dd",
            label: "data(label)",
            "font-family": "IBM Plex Sans, ui-sans-serif, system-ui",
            "font-size": 10,
            "font-weight": 500,
            "text-background-color": "#09110f",
            "text-background-opacity": 0.82,
            "text-background-padding": "3px",
            "text-margin-y": 13,
            "text-max-width": "110px",
            "text-wrap": "ellipsis",
            height: "18px",
            width: "18px",
          },
        },
        {
          selector: "edge",
          style: {
            width: 1,
            "line-color": "#476057",
            "target-arrow-color": "#476057",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            opacity: 0.68,
          },
        },
        {
          selector: ".path",
          style: {
            "background-color": "#f2d36f",
            "line-color": "#f2d36f",
            "target-arrow-color": "#f2d36f",
            opacity: 1,
            "z-index": 20,
          },
        },
        { selector: ":selected", style: { "border-color": "#f4efe0", "border-width": 4 } },
      ],
      layout: {
        name: view.default_layout === "dagre" ? "breadthfirst" : "cose",
        animate: false,
        fit: true,
        padding: 42,
      },
    });
    core.current = cy;
    cy.on("tap", "node", (event) => onSelect(event.target.data() as GraphNode));
    onReady(cy);
    return () => {
      cy.destroy();
      core.current = null;
    };
  }, [elements, onReady, onSelect, view.default_layout]);

  return (
    <div
      className="graph-canvas"
      ref={container}
      role="region"
      aria-label="Interactive evidence graph"
    />
  );
}
