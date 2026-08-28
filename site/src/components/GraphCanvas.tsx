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

const optimizationLayout: GraphPresentation = {
  stages: [
    { label: "Optimizations", types: ["optimization"] },
    { label: "Bottlenecks", types: ["bottleneck"] },
    { label: "Experiments", types: ["experiment"] },
    { label: "Comparisons", types: ["comparison"] },
    { label: "Findings", types: ["finding"] },
  ],
  intro: "",
  relations: [],
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

function displayIdentifier(node: CanvasNode): string {
  if (node.synthetic) return `R×${node.member_ids?.length ?? 0}`;
  return artifactCode(node.artifact_ref);
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
    const columnCount = ranked.length > 18 ? 4 : ranked.length > 6 ? 2 : 1;
    const columns = Array.from({ length: columnCount }, (_, columnIndex) =>
      ranked.filter((_, index) => index % columnCount === columnIndex),
    );
    columns.forEach((column, columnIndex) => {
      const nodeHeight = 64;
      const runAwareLayout = presentation.compact_runs !== undefined;
      const verticalGap = runAwareLayout ? 48 : 36;
      const horizontalGap = runAwareLayout ? 420 : 320;
      const totalHeight = column.length * nodeHeight + Math.max(0, column.length - 1) * verticalGap;
      let cursor = -totalHeight / 2;
      column.forEach((node) => {
        positions.set(node.id, {
          x:
            rank * horizontalGap +
            (columnCount > 1 ? (columnIndex - (columnCount - 1) / 2) * 168 : 0),
          y: cursor + nodeHeight / 2,
        });
        cursor += nodeHeight + verticalGap;
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
  const previousViewport = useRef<{
    viewId: GraphView["id"];
    zoom: number;
    pan: { x: number; y: number };
  } | null>(null);
  const [expandedRunGroups, setExpandedRunGroups] = useState<Set<string>>(new Set());
  const [tooltip, setTooltip] = useState<{
    code: string;
    label: string;
    type: string;
    x: number;
    y: number;
    synthetic: boolean;
  } | null>(null);
  const viewNodes = useMemo(() => new Set(view.node_ids), [view]);
  const viewEdges = useMemo(() => new Set(view.edge_ids), [view]);
  const presentation = view.filters.presentation;
  const layoutPresentation = presentation ?? (view.id === "optimization" ? optimizationLayout : undefined);

  useEffect(() => {
    setExpandedRunGroups(new Set());
    setTooltip(null);
  }, [view.id]);

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
    const positions = layoutPresentation
      ? layeredPositions(visibleNodes, layoutPresentation)
      : new Map();
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
          displayLabel: displayIdentifier(node),
        },
        position: positions.get(node.id),
        classes: [
          layoutPresentation ? "guided-node" : "dot",
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
    layoutPresentation,
    presentation,
    query,
    selectedTypes,
    showNegative,
    viewEdges,
    viewNodes,
  ]);

  useEffect(() => {
    if (!container.current) return;
    const layered = Boolean(layoutPresentation);
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
            "border-color": "#24312c",
            "border-width": 2,
            color: "#17231f",
            label: "data(displayLabel)",
            "font-family": "IBM Plex Sans, ui-sans-serif, system-ui",
            "font-size": 8.5,
            "font-weight": 800,
            "text-halign": "center",
            "text-valign": "center",
            "text-max-width": "46px",
            "text-wrap": "ellipsis",
            height: "50px",
            width: "50px",
          },
        },
        {
          selector: "node.guided-node",
          style: {
            shape: "ellipse",
            width: "64px",
            height: "64px",
            "font-size": 8.2,
            "text-max-width": "60px",
          },
        },
        {
          selector: "node.run-group",
          style: {
            "border-style": "dashed",
            "font-size": 9,
          },
        },
        {
          selector: "node.selected-config",
          style: {
            "border-color": "#27795c",
            "border-width": 4,
          },
        },
        {
          selector: "edge",
          style: {
            width: 2.1,
            "line-color": "#91a19a",
            "target-arrow-color": "#71877e",
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.95,
            "curve-style": "bezier",
            opacity: 0.82,
          },
        },
        {
          selector: "edge.context",
          style: {
            label: "data(displayRelation)",
            color: "#25342e",
            "font-size": 8.5,
            "font-weight": 650,
            "text-background-color": "#ffffff",
            "text-background-opacity": 0.96,
            "text-background-padding": "4px",
            "line-color": "#465f55",
            "target-arrow-color": "#465f55",
            width: 2.8,
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
            "border-color": "#b77919",
            "border-width": 4,
            "line-color": "#d0922d",
            "target-arrow-color": "#d0922d",
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
          style: { "border-color": "#b77919", "border-width": 4, "z-index": 30 },
        },
        { selector: ":selected", style: { "border-color": "#17231f", "border-width": 4 } },
      ],
      layout: layered
        ? { name: "preset", fit: !narrow, padding: 38 }
        : {
            name: view.default_layout === "dagre" ? "breadthfirst" : "cose",
            animate: false,
            fit: true,
            padding: 60,
            idealEdgeLength: view.id === "optimization" ? 135 : 120,
            nodeRepulsion: view.id === "optimization" ? 550_000 : 450_000,
            componentSpacing: view.id === "optimization" ? 120 : 100,
            gravity: 0.14,
            numIter: 1_200,
          },
    });
    core.current = cy;
    if (layered && narrow) {
      cy.zoom(0.72);
      const firstStage = layoutPresentation?.stages[0];
      const start = cy
        .nodes()
        .filter((node) => Boolean(firstStage?.types.includes(node.data("type"))));
      cy.center(start.length ? start : cy.nodes());
    } else {
      const minimumReadableZoom = layered
        ? layoutPresentation?.compact_runs
          ? 0.58
          : 0.58
        : 0;
      if (cy.zoom() < minimumReadableZoom) {
        cy.zoom(minimumReadableZoom);
        cy.center(cy.nodes());
      }
    }
    const storedViewport = previousViewport.current;
    if (storedViewport?.viewId === view.id) {
      cy.zoom(storedViewport.zoom);
      cy.pan(storedViewport.pan);
    }
    const exposeViewport = () => {
      if (!container.current) return;
      const pan = cy.pan();
      container.current.dataset.zoom = cy.zoom().toFixed(4);
      container.current.dataset.panX = pan.x.toFixed(2);
      container.current.dataset.panY = pan.y.toFixed(2);
    };
    cy.on("zoom pan", exposeViewport);
    exposeViewport();
    cy.on("tap", "node", (event) => {
      const data = event.target.data() as CanvasNode;
      if (data.synthetic) {
        setExpandedRunGroups((current) => new Set(current).add(data.id));
        return;
      }
      onSelect(data);
    });
    const showTooltip = (event: cytoscape.EventObject) => {
      const data = event.target.data() as CanvasNode;
      const position = event.target.renderedPosition();
      setTooltip({
        code: displayIdentifier(data),
        label: data.label,
        type: data.type,
        x: position.x,
        y: position.y,
        synthetic: Boolean(data.synthetic),
      });
    };
    cy.on("mouseover", "node", (event) => {
      event.target.connectedEdges().addClass("context");
      showTooltip(event);
    });
    cy.on("mousemove", "node", showTooltip);
    cy.on("mouseout", "node", (event) => {
      event.target.connectedEdges().removeClass("context");
      setTooltip(null);
    });
    onReady(cy);
    return () => {
      previousViewport.current = {
        viewId: view.id,
        zoom: cy.zoom(),
        pan: cy.pan(),
      };
      cy.destroy();
      core.current = null;
    };
  }, [elements, layoutPresentation, onReady, onSelect, view.default_layout, view.id]);

  const accessibleNodes = elements.filter(
    (element): element is ElementDefinition & { data: CanvasNode } =>
      "type" in element.data && typeof element.data.type === "string",
  );

  return (
    <div className={`graph-surface${layoutPresentation ? " with-presentation" : ""}`}>
      <div
        className="graph-canvas"
        ref={container}
        role="img"
        aria-label="Interactive evidence graph. Use the node navigator for keyboard access."
        data-rendered-nodes={accessibleNodes.length}
        data-run-groups={elements.filter((element) => element.data.synthetic === true).length}
      />
      {tooltip && (
        <div className="node-tooltip" style={{ left: tooltip.x, top: tooltip.y }} role="tooltip">
          <strong>{tooltip.code}</strong>
          <span>{tooltip.label}</span>
          <small>
            {tooltip.synthetic
              ? "Select to reveal individual runs"
              : `Select to open complete ${tooltip.type.replaceAll("_", " ")} details`}
          </small>
        </div>
      )}
      <nav className="graph-node-index" aria-label="Graph node navigator">
        {accessibleNodes.map((element) => {
          const node = element.data;
          return (
            <button
              key={node.id}
              onFocus={() => {
                const element = core.current?.getElementById(node.id);
                if (!element?.length) return;
                const position = element.renderedPosition();
                element.connectedEdges().addClass("context");
                setTooltip({
                  code: displayIdentifier(node),
                  label: node.label,
                  type: node.type,
                  x: position.x,
                  y: position.y,
                  synthetic: Boolean(node.synthetic),
                });
              }}
              onBlur={() => {
                core.current?.getElementById(node.id).connectedEdges().removeClass("context");
                setTooltip(null);
              }}
              onClick={() => {
                if (node.synthetic) {
                  setExpandedRunGroups((current) => new Set(current).add(node.id));
                } else {
                  onSelect(node);
                }
              }}
            >
              {displayIdentifier(node)} — {node.label}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
