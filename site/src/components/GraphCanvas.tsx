import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";

import type { GraphData, GraphEdge, GraphNode, GraphPresentation, GraphView } from "../types";

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

interface CanvasNode extends GraphNode {
  synthetic?: boolean;
  member_ids?: string[];
}

function artifactCode(reference: string): string {
  return reference.split("/").at(-1)?.replace(/@v\d+$/, "") ?? reference;
}

function compactLabel(value: string, limit = 46): string {
  if (value.length <= limit) return value;
  const shortened = value.slice(0, limit - 1);
  const boundary = shortened.lastIndexOf(" ");
  return `${shortened.slice(0, boundary > 25 ? boundary : limit - 1)}…`;
}

function displayLabel(node: CanvasNode): string {
  if (node.synthetic) return compactLabel(node.label, 42);
  const identifier = artifactCode(node.artifact_ref);
  if (node.type === "run") return identifier;
  return `${identifier}\n${compactLabel(node.label)}`;
}

function isNegative(node: GraphNode): boolean {
  return node.tags.some((tag) =>
    ["degradation", "no_significant_effect", "inconclusive", "contradicted"].includes(tag),
  );
}

function presentationEdgeLabel(edge: GraphEdge, nodes: Map<string, CanvasNode>): string {
  if (edge.relation === "USES_CONFIGURATION" && nodes.get(edge.source)?.type === "decision") {
    return "selects";
  }
  return edge.relation.replaceAll("_", " ").toLowerCase();
}

function runGroups(
  graph: GraphData,
  nodes: CanvasNode[],
  expanded: Set<string>,
): { nodes: CanvasNode[]; endpoint: Map<string, string> } {
  const experimentByRun = new Map<string, string>();
  const configurationByRun = new Map<string, string>();
  for (const edge of graph.edges) {
    if (edge.relation === "HAS_RUN") experimentByRun.set(edge.target, edge.source);
    if (edge.relation === "USES_CONFIGURATION") configurationByRun.set(edge.source, edge.target);
  }

  const groups = new Map<string, CanvasNode[]>();
  for (const node of nodes) {
    if (node.type !== "run") continue;
    const experiment = experimentByRun.get(node.id);
    const configuration = configurationByRun.get(node.id);
    if (!experiment || !configuration) continue;
    const key = `${experiment}|${configuration}`;
    const members = groups.get(key) ?? [];
    members.push(node);
    groups.set(key, members);
  }

  const endpoint = new Map<string, string>();
  const collapsedMembers = new Set<string>();
  const syntheticNodes: CanvasNode[] = [];
  for (const [key, members] of [...groups].sort(([left], [right]) => left.localeCompare(right))) {
    if (members.length < 2) continue;
    const [experiment, configuration] = key.split("|");
    const groupId = `presentation://run-group/${artifactCode(experiment)}/${artifactCode(configuration)}`;
    if (expanded.has(groupId)) continue;
    const accepted = members.filter((member) => member.status === "accepted").length;
    const configurationNode = graph.nodes.find((node) => node.id === configuration);
    for (const member of members) {
      endpoint.set(member.id, groupId);
      collapsedMembers.add(member.id);
    }
    syntheticNodes.push({
      id: groupId,
      type: "run",
      label: `${artifactCode(configuration)} · ${members.length} reps`,
      status: accepted === members.length ? "accepted" : "mixed",
      source_path: members[0].source_path,
      artifact_ref: groupId,
      summary: `${members.length} runs for ${configurationNode?.label ?? artifactCode(configuration)}. Select to expand.`,
      tags: ["replicate-group"],
      study: members[0].study,
      synthetic: true,
      member_ids: members.map((member) => member.id).sort(),
    });
  }

  return {
    nodes: [...nodes.filter((node) => !collapsedMembers.has(node.id)), ...syntheticNodes],
    endpoint,
  };
}

function layeredPositions(
  nodes: CanvasNode[],
  presentation: GraphPresentation,
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  presentation.stages.forEach((stage, rank) => {
    const ranked = nodes
      .filter((node) => stage.types.includes(node.type))
      .sort((left, right) => left.id.localeCompare(right.id));
    const usesSubcolumns = ranked.length > 6;
    const rows = usesSubcolumns ? Math.ceil(ranked.length / 2) : ranked.length;
    const verticalGap = ranked.length >= 6 ? 78 : 88;
    ranked.forEach((node, index) => {
      positions.set(node.id, {
        x: rank * 200 + (usesSubcolumns ? (index % 2 === 0 ? -60 : 60) : 0),
        y:
          ((usesSubcolumns ? Math.floor(index / 2) : index) - (rows - 1) / 2) *
          verticalGap,
      });
    });
  });
  return positions;
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
  const [expandedRunGroups, setExpandedRunGroups] = useState<Set<string>>(new Set());
  const viewNodes = useMemo(() => new Set(view.node_ids), [view]);
  const viewEdges = useMemo(() => new Set(view.edge_ids), [view]);
  const presentation = view.filters.presentation;

  useEffect(() => setExpandedRunGroups(new Set()), [view.id]);

  const elements = useMemo<ElementDefinition[]>(() => {
    const normalizedQuery = query.trim().toLowerCase();
    let visibleNodes: CanvasNode[] = graph.nodes.filter(
      (node) =>
        viewNodes.has(node.id) &&
        (selectedTypes.size === 0 || selectedTypes.has(node.type)) &&
        (showNegative || !isNegative(node)),
    );
    let endpoint = new Map<string, string>();
    if (presentation?.compact_runs) {
      const grouped = runGroups(graph, visibleNodes, expandedRunGroups);
      visibleNodes = grouped.nodes;
      endpoint = grouped.endpoint;
    }

    const nodeIds = new Set(visibleNodes.map((node) => node.id));
    const nodeById = new Map(visibleNodes.map((node) => [node.id, node]));
    const selectedConfigurations = new Set(
      graph.edges
        .filter(
          (edge) =>
            edge.relation === "USES_CONFIGURATION" &&
            graph.nodes.some((node) => node.id === edge.source && node.type === "decision"),
        )
        .map((edge) => edge.target),
    );
    const positions = presentation ? layeredPositions(visibleNodes, presentation) : new Map();
    const nodeElements: ElementDefinition[] = visibleNodes.map((node) => {
      const matches =
        !normalizedQuery ||
        `${node.label} ${node.summary} ${node.tags.join(" ")}`
          .toLowerCase()
          .includes(normalizedQuery);
      return {
        data: {
          ...node,
          color: colors[node.type] ?? "#c8d0c8",
          displayLabel: displayLabel(node),
        },
        position: positions.get(node.id),
        classes: [
          presentation ? "card" : "dot",
          node.synthetic ? "run-group" : "",
          selectedConfigurations.has(node.id) ? "selected-config" : "",
          highlighted.has(node.id) ? "path" : "",
          normalizedQuery ? (matches ? "search-match" : "search-muted") : "",
        ]
          .filter(Boolean)
          .join(" "),
      };
    });

    const edges = new Map<string, GraphEdge>();
    for (const edge of graph.edges) {
      if (!viewEdges.has(edge.id)) continue;
      const source = endpoint.get(edge.source) ?? edge.source;
      const target = endpoint.get(edge.target) ?? edge.target;
      if (source === target || !nodeIds.has(source) || !nodeIds.has(target)) continue;
      const key = `${source}|${edge.relation}|${target}`;
      if (!edges.has(key)) {
        edges.set(key, {
          ...edge,
          id: source === edge.source && target === edge.target ? edge.id : `presentation:${key}`,
          source,
          target,
        });
      }
    }
    const edgeElements: ElementDefinition[] = [...edges.values()].map((edge) => {
      const sourceMuted = normalizedQuery && !nodeElements.find(
        (element) => element.data.id === edge.source && !String(element.classes).includes("search-muted"),
      );
      const targetMuted = normalizedQuery && !nodeElements.find(
        (element) => element.data.id === edge.target && !String(element.classes).includes("search-muted"),
      );
      return {
        data: {
          ...edge,
          displayRelation: presentationEdgeLabel(edge, nodeById),
        },
        classes: [
          highlighted.has(edge.id) ||
          (highlighted.has(edge.source) && highlighted.has(edge.target))
            ? "path"
            : "",
          sourceMuted && targetMuted ? "search-muted" : "",
          `relation-${edge.relation.toLowerCase().replaceAll("_", "-")}`,
        ]
          .filter(Boolean)
          .join(" "),
      };
    });
    return [...nodeElements, ...edgeElements];
  }, [
    expandedRunGroups,
    graph,
    highlighted,
    presentation,
    query,
    selectedTypes,
    showNegative,
    viewEdges,
    viewNodes,
  ]);

  useEffect(() => {
    if (!container.current) return;
    const layered = Boolean(presentation);
    const narrow = container.current.clientWidth < 700;
    const cy = cytoscape({
      container: container.current,
      elements,
      minZoom: layered ? 0.35 : 0.15,
      maxZoom: 2.5,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)",
            "border-color": "#09110f",
            "border-width": 2,
            color: "#ece9dd",
            label: "data(displayLabel)",
            "font-family": "IBM Plex Sans, ui-sans-serif, system-ui",
            "font-size": 10,
            "font-weight": 600,
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
          selector: "node.card",
          style: {
            shape: "roundrectangle",
            width: "156px",
            height: "58px",
            "background-color": "#13201c",
            "border-color": "data(color)",
            "border-width": 2,
            color: "#f0eee4",
            "font-size": 12,
            "font-weight": 600,
            "text-background-opacity": 0,
            "text-margin-y": 0,
            "text-max-width": "134px",
            "text-valign": "center",
            "text-wrap": "wrap",
          },
        },
        {
          selector: "node.run-group",
          style: {
            width: "106px",
            "border-style": "dashed",
            "background-color": "#182a23",
            "font-size": 11,
          },
        },
        {
          selector: "node.selected-config",
          style: {
            "border-color": "#59b894",
            "border-width": 4,
            "background-color": "#173026",
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.6,
            "line-color": "#557168",
            "target-arrow-color": "#779288",
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.75,
            "curve-style": layered ? "taxi" : "bezier",
            "taxi-direction": "rightward",
            "taxi-turn": 24,
            opacity: 0.76,
          },
        },
        {
          selector: "edge.context",
          style: {
            label: "data(displayRelation)",
            color: "#d7ddd8",
            "font-size": 8,
            "text-background-color": "#09110f",
            "text-background-opacity": 0.94,
            "text-background-padding": "3px",
            "line-color": "#91a99f",
            "target-arrow-color": "#91a99f",
            opacity: 1,
            "z-index": 12,
          },
        },
        {
          selector: "edge.relation-supports",
          style: { "line-color": "#bca866", "target-arrow-color": "#bca866" },
        },
        {
          selector: "edge.relation-justifies",
          style: { "line-color": "#d7bb64", "target-arrow-color": "#d7bb64", width: 2.2 },
        },
        {
          selector: "edge.relation-uses-configuration",
          style: { "line-color": "#59b894", "target-arrow-color": "#59b894", width: 2.8 },
        },
        {
          selector: "edge.relation-rejects",
          style: {
            "line-color": "#8e665e",
            "target-arrow-color": "#8e665e",
            "line-style": "dashed",
            opacity: 0.58,
          },
        },
        {
          selector: ".path",
          style: {
            "border-color": "#f2d36f",
            "border-width": 4,
            "line-color": "#f2d36f",
            "target-arrow-color": "#f2d36f",
            opacity: 1,
            "z-index": 20,
          },
        },
        {
          selector: ".search-muted",
          style: { opacity: 0.12 },
        },
        {
          selector: ".search-match",
          style: { "border-color": "#f2d36f", "border-width": 4, "z-index": 30 },
        },
        { selector: ":selected", style: { "border-color": "#f4efe0", "border-width": 4 } },
      ],
      layout: layered
        ? { name: "preset", fit: !narrow, padding: 38 }
        : {
            name: view.default_layout === "dagre" ? "breadthfirst" : "cose",
            animate: false,
            fit: true,
            padding: 54,
          },
    });
    core.current = cy;
    if (layered && narrow) {
      cy.zoom(0.72);
      const firstStage = presentation?.stages[0];
      const start = cy
        .nodes()
        .filter((node) => Boolean(firstStage?.types.includes(node.data("type"))));
      cy.center(start.length ? start : cy.nodes());
    }
    cy.on("tap", "node", (event) => {
      const data = event.target.data() as CanvasNode;
      if (data.synthetic) {
        setExpandedRunGroups((current) => new Set(current).add(data.id));
        return;
      }
      onSelect(data);
    });
    cy.on("mouseover", "node", (event) => event.target.connectedEdges().addClass("context"));
    cy.on("mouseout", "node", (event) => event.target.connectedEdges().removeClass("context"));
    onReady(cy);
    return () => {
      cy.destroy();
      core.current = null;
    };
  }, [elements, onReady, onSelect, presentation, view.default_layout]);

  return (
    <div
      className={`graph-canvas${presentation ? " with-presentation" : ""}`}
      ref={container}
      role="region"
      aria-label="Interactive evidence graph"
      data-rendered-nodes={elements.filter((element) => "type" in element.data).length}
      data-run-groups={elements.filter((element) => element.data.synthetic === true).length}
    />
  );
}
