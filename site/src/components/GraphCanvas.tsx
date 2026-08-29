import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";

import { relationDescription, relationLabel } from "../relations";
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
  selectedId?: string;
  tourActive: boolean;
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

function focusTourNode(core: Core, nodeId: string, container: HTMLElement): void {
  const node = core.getElementById(nodeId);
  if (!node.length) return;
  core.elements().unselect();
  node.select();
  const neighborhood = node.closedNeighborhood();
  core.fit(neighborhood.length ? neighborhood : node, 110);

  const panel = document.querySelector<HTMLElement>(".study-tour");
  if (!panel) return;
  const canvasRect = container.getBoundingClientRect();
  const panelRect = panel.getBoundingClientRect();
  const margin = 48;
  const overlapsCanvas =
    panelRect.left < canvasRect.right &&
    panelRect.right > canvasRect.left &&
    panelRect.top < canvasRect.bottom &&
    panelRect.bottom > canvasRect.top;
  let visibleLeft = margin;
  let visibleRight = canvasRect.width - margin;
  let visibleTop = margin;
  let visibleBottom = canvasRect.height - margin;

  if (overlapsCanvas) {
    const overlapWidth =
      Math.min(panelRect.right, canvasRect.right) - Math.max(panelRect.left, canvasRect.left);
    const preferVerticalSpace = overlapWidth >= canvasRect.width * 0.72;
    if (
      preferVerticalSpace &&
      panelRect.top + panelRect.height / 2 >= canvasRect.top + canvasRect.height / 2
    ) {
      visibleBottom = Math.min(visibleBottom, panelRect.top - canvasRect.top - margin);
    } else if (preferVerticalSpace) {
      visibleTop = Math.max(visibleTop, panelRect.bottom - canvasRect.top + margin);
    } else if (panelRect.right >= canvasRect.right - margin) {
      visibleRight = Math.min(visibleRight, panelRect.left - canvasRect.left - margin);
    } else if (panelRect.left <= canvasRect.left + margin) {
      visibleLeft = Math.max(visibleLeft, panelRect.right - canvasRect.left + margin);
    } else if (panelRect.bottom >= canvasRect.bottom - margin) {
      visibleBottom = Math.min(visibleBottom, panelRect.top - canvasRect.top - margin);
    } else {
      visibleTop = Math.max(visibleTop, panelRect.bottom - canvasRect.top + margin);
    }
  }

  if (visibleRight > visibleLeft && visibleBottom > visibleTop) {
    const position = node.renderedPosition();
    const shift = { x: 0, y: 0 };
    if (position.x < visibleLeft) shift.x = visibleLeft - position.x;
    else if (position.x > visibleRight) shift.x = visibleRight - position.x;
    if (position.y < visibleTop) shift.y = visibleTop - position.y;
    else if (position.y > visibleBottom) shift.y = visibleBottom - position.y;
    if (shift.x || shift.y) core.panBy(shift);
  }

  const adjusted = node.renderedPosition();
  container.dataset.tourNodeVisible = String(
    adjusted.x >= visibleLeft &&
      adjusted.x <= visibleRight &&
      adjusted.y >= visibleTop &&
      adjusted.y <= visibleBottom,
  );
}

function edgeTooltipPosition(
  position: { x: number; y: number },
  container: HTMLElement | null,
): { x: number; y: number } {
  if (!container) return position;
  return {
    x: Math.min(Math.max(12, position.x), Math.max(12, container.clientWidth - 364)),
    y: Math.min(Math.max(96, position.y), Math.max(96, container.clientHeight - 96)),
  };
}

export function GraphCanvas({
  graph,
  view,
  query,
  selectedTypes,
  showNegative,
  highlighted,
  selectedId,
  tourActive,
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
  const [tooltip, setTooltip] = useState<
    | {
        kind: "node";
        code: string;
        label: string;
        type: string;
        x: number;
        y: number;
        synthetic: boolean;
      }
    | {
        kind: "edge";
        relation: string;
        source: string;
        target: string;
        description: string;
        assertion: string;
        confidence: string;
        x: number;
        y: number;
      }
    | null
  >(null);
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
    const selectedNeighbors = new Set<string>();
    if (selectedId && nodeIds.has(selectedId)) {
      for (const edge of graph.edges) {
        if (!viewEdges.has(edge.id)) continue;
        const source = endpoint.get(edge.source) ?? edge.source;
        const target = endpoint.get(edge.target) ?? edge.target;
        if (source === selectedId && nodeIds.has(target)) selectedNeighbors.add(target);
        if (target === selectedId && nodeIds.has(source)) selectedNeighbors.add(source);
      }
    }
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
          highlighted.size > 0 && !highlighted.has(node.id) ? "path-muted" : "",
          node.id === selectedId ? "selected-node" : "",
          selectedNeighbors.has(node.id) ? "selected-neighbor" : "",
          selectedId &&
          highlighted.size === 0 &&
          node.id !== selectedId &&
          !selectedNeighbors.has(node.id)
            ? "selection-muted"
            : "",
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
      const isPath =
        highlighted.has(edge.id) ||
        (highlighted.has(edge.source) && highlighted.has(edge.target));
      const isSelectedEdge = edge.source === selectedId || edge.target === selectedId;
      return {
        data: {
          ...edge,
          displayRelation: presentationEdgeLabel(edge, nodeById),
        },
        classes: [
          isPath ? "path" : "",
          highlighted.size > 0 && !isPath ? "path-muted" : "",
          isSelectedEdge ? "selected-edge" : "",
          selectedId && highlighted.size === 0 && !isSelectedEdge ? "selection-muted" : "",
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
    selectedId,
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
            "font-family":
              "Avenir Next, Segoe UI Variable, Segoe UI, Helvetica Neue, Arial, sans-serif",
            "font-size": 9.5,
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
            "font-size": 9.5,
            "text-max-width": "60px",
          },
        },
        {
          selector: "node.run-group",
          style: {
            "border-style": "dashed",
            "font-size": 10,
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
            "font-size": 9.5,
            "font-weight": 600,
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
          selector: ".selection-muted",
          style: { opacity: 0.13 },
        },
        {
          selector: ".path-muted",
          style: { opacity: 0.055 },
        },
        {
          selector: "node.selected-neighbor",
          style: {
            "border-color": "#425d52",
            "border-width": 3,
            opacity: 0.92,
            "z-index": 25,
          },
        },
        {
          selector: "edge.selected-edge",
          style: {
            "line-color": "#263c34",
            "target-arrow-color": "#263c34",
            width: 3.8,
            opacity: 1,
            "z-index": 24,
          },
        },
        {
          selector: "node.selected-node",
          style: {
            "border-color": "#17231f",
            "border-width": 5,
            "underlay-color": "#e8b35a",
            "underlay-opacity": 0.36,
            "underlay-padding": 11,
            opacity: 1,
            "z-index": 32,
          },
        },
        {
          selector: "node.edge-endpoint",
          style: {
            "border-color": "#27795c",
            "border-width": 4,
            "underlay-color": "#90c8ad",
            "underlay-opacity": 0.25,
            "underlay-padding": 7,
            opacity: 1,
            "z-index": 34,
          },
        },
        {
          selector: "edge.edge-hover",
          style: {
            label: "data(displayRelation)",
            color: "#17231f",
            "font-size": 10.5,
            "font-weight": 700,
            "text-background-color": "#ffffff",
            "text-background-opacity": 1,
            "text-background-padding": "5px",
            "line-color": "#27795c",
            "target-arrow-color": "#27795c",
            width: 4.4,
            opacity: 1,
            "z-index": 36,
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
          selector: "node.selected-node.path",
          style: {
            "border-color": "#17231f",
            "underlay-color": "#d0922d",
            "underlay-opacity": 0.44,
            "z-index": 40,
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
        {
          selector: ":selected",
          style: { "border-color": "#17231f", "border-width": 5, "z-index": 40 },
        },
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
    let tourFrame = 0;
    if (tourActive && selectedId) {
      tourFrame = window.requestAnimationFrame(() => {
        if (window.innerWidth <= 900) {
          container.current
            ?.closest(".graph-frame")
            ?.scrollIntoView({ block: "start", behavior: "auto" });
        }
        tourFrame = window.requestAnimationFrame(() => {
          if (container.current) focusTourNode(cy, selectedId, container.current);
        });
      });
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
        kind: "node",
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
    const showEdgeTooltip = (event: cytoscape.EventObject) => {
      const edge = event.target;
      const data = edge.data() as GraphEdge;
      const source = edge.source().data() as CanvasNode;
      const target = edge.target().data() as CanvasNode;
      const position = event.renderedPosition ?? edge.renderedMidpoint();
      const tooltipPosition = edgeTooltipPosition(position, container.current);
      setTooltip({
        kind: "edge",
        relation: relationLabel(data.relation),
        source: `${displayIdentifier(source)} · ${source.label}`,
        target: `${displayIdentifier(target)} · ${target.label}`,
        description: relationDescription(data.relation),
        assertion: data.assertion_level.replaceAll("_", " "),
        confidence: data.confidence,
        x: tooltipPosition.x,
        y: tooltipPosition.y,
      });
    };
    cy.on("mouseover", "edge", (event) => {
      event.target.addClass("edge-hover");
      event.target.source().addClass("edge-endpoint");
      event.target.target().addClass("edge-endpoint");
      showEdgeTooltip(event);
    });
    cy.on("mousemove", "edge", showEdgeTooltip);
    cy.on("mouseout", "edge", (event) => {
      event.target.removeClass("edge-hover");
      event.target.source().removeClass("edge-endpoint");
      event.target.target().removeClass("edge-endpoint");
      setTooltip(null);
    });
    onReady(cy);
    return () => {
      window.cancelAnimationFrame(tourFrame);
      previousViewport.current = {
        viewId: view.id,
        zoom: cy.zoom(),
        pan: cy.pan(),
      };
      cy.destroy();
      core.current = null;
    };
  }, [
    elements,
    layoutPresentation,
    onReady,
    onSelect,
    selectedId,
    tourActive,
    view.default_layout,
    view.id,
  ]);

  const accessibleNodes = elements.filter(
    (element): element is ElementDefinition & { data: CanvasNode } =>
      "type" in element.data && typeof element.data.type === "string",
  );
  const accessibleEdges = elements.filter(
    (element): element is ElementDefinition & { data: GraphEdge } =>
      "relation" in element.data && typeof element.data.relation === "string",
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
        data-highlighted-elements={highlighted.size}
        data-selected-id={selectedId ?? ""}
        data-tour-node-visible={tourActive ? "pending" : undefined}
        data-dimmed-elements={
          elements.filter((element) =>
            String(element.classes).match(/(?:selection-muted|path-muted)/),
          ).length
        }
      />
      {tooltip?.kind === "node" && (
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
      {tooltip?.kind === "edge" && (
        <div className="relation-tooltip" style={{ left: tooltip.x, top: tooltip.y }} role="tooltip">
          <div>
            <strong>{tooltip.relation}</strong>
            <span>{tooltip.assertion} · {tooltip.confidence} confidence</span>
          </div>
          <p>{tooltip.description}</p>
          <small>{tooltip.source}<i aria-hidden="true">→</i>{tooltip.target}</small>
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
                  kind: "node",
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
      <nav className="graph-node-index" aria-label="Graph relationship navigator">
        {accessibleEdges.map((element) => {
          const edge = element.data;
          const source = graph.nodes.find((node) => node.id === edge.source);
          const target = graph.nodes.find((node) => node.id === edge.target);
          return (
            <button
              key={edge.id}
              onFocus={() => {
                const renderedEdge = core.current?.getElementById(edge.id);
                if (!renderedEdge?.length) return;
                renderedEdge.addClass("edge-hover");
                renderedEdge.source().addClass("edge-endpoint");
                renderedEdge.target().addClass("edge-endpoint");
                const position = renderedEdge.renderedMidpoint();
                const tooltipPosition = edgeTooltipPosition(position, container.current);
                setTooltip({
                  kind: "edge",
                  relation: relationLabel(edge.relation),
                  source: `${source ? displayIdentifier(source) : artifactCode(edge.source)} · ${source?.label ?? "Source entity"}`,
                  target: `${target ? displayIdentifier(target) : artifactCode(edge.target)} · ${target?.label ?? "Target entity"}`,
                  description: relationDescription(edge.relation),
                  assertion: edge.assertion_level.replaceAll("_", " "),
                  confidence: edge.confidence,
                  x: tooltipPosition.x,
                  y: tooltipPosition.y,
                });
              }}
              onBlur={() => {
                const renderedEdge = core.current?.getElementById(edge.id);
                renderedEdge?.removeClass("edge-hover");
                renderedEdge?.source().removeClass("edge-endpoint");
                renderedEdge?.target().removeClass("edge-endpoint");
                setTooltip(null);
              }}
            >
              {source ? displayIdentifier(source) : artifactCode(edge.source)} {relationLabel(edge.relation)}{" "}
              {target ? displayIdentifier(target) : artifactCode(edge.target)}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
