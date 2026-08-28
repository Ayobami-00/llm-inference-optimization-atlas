import type { Core } from "cytoscape";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { GraphCanvas } from "./components/GraphCanvas";
import { loadAtlas, loadEntity } from "./data";
import type { AtlasData, EntityDetail, GraphNode, GraphView } from "./types";

const viewOrder: GraphView["id"][] = [
  "story",
  "bottleneck",
  "optimization",
  "evidence",
  "deployment",
];

function titleCase(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function relationLabel(value: string): string {
  if (value === "USES_CONFIGURATION") return "selects / uses";
  return value.replaceAll("_", " ").toLowerCase();
}

const viewNarratives: Record<GraphView["id"], [string, string, string]> = {
  story: [
    "This view follows the study from its frozen workload through experiments and comparisons to findings and a deployment decision.",
    "Each branch represents a research question and connects the measured result to its carefully scoped interpretation.",
    "Read from left to right, then select any circle to open its complete evidence record without moving the graph.",
  ],
  bottleneck: [
    "This view maps observed workload and system pressure to the bottlenecks that may explain it.",
    "The links expose diagnostic signals, competing explanations, and the optimization families that could address each constraint.",
    "Treat theoretical and observational links as investigation paths until experimental evidence validates the bottleneck.",
  ],
  optimization: [
    "This view organizes optimization mechanisms around the bottlenecks they are designed to target.",
    "Evidence links reveal where a technique improved, degraded, or failed to change a measured outcome under a specific scope.",
    "Use the graph to separate broad applicability from experimentally supported results and their known boundaries.",
  ],
  evidence: [
    "This view exposes the complete evidence chain from a falsifiable hypothesis to experiments, replicate runs, comparisons, and findings.",
    "Repeated runs are grouped until opened so the experimental structure remains legible without hiding its replication depth.",
    "Follow the arrows from left to right to see exactly which measurements support each scoped claim.",
  ],
  deployment: [
    "This view explains how accepted findings lead to a deployment decision and the configuration it selects or rejects.",
    "The decision is connected to its measured trade-offs, supporting evidence, and alternative configurations rather than presented as a standalone recommendation.",
    "Use the highlighted decision path to inspect the rationale from outcome back to evidence.",
  ],
  all: [
    "This view contains the complete compiled evidence graph, including scientific evidence, structural context, and external sources.",
    "It is intentionally dense so relationships omitted from the guided views remain available for open-ended investigation.",
    "Use search and entity filters to isolate a question, then select a node to inspect its full record and provenance.",
  ],
};

const globalStoryNarrative: [string, string, string] = [
  "This view connects every workload archetype to the concrete workload and study that represents it in the Atlas.",
  "Each branch presents the high-level research story while omitting individual runs, configurations, and implementation detail.",
  "Read from left to right to see which studies exist and which deployment decisions their evidence produced.",
];

function artifactCode(reference: string): string {
  return reference.split("/").at(-1)?.replace(/@v\d+$/, "") ?? reference;
}

function entityPrefix(type: string, nodes: GraphNode[]): string {
  const representative = nodes.find((node) => node.type === type);
  const identifier = representative ? artifactCode(representative.artifact_ref) : "";
  return identifier.match(/^[A-Z]+/)?.[0] ?? type.slice(0, 3).toUpperCase();
}

function isNegativeNode(node: GraphNode): boolean {
  return node.tags.some((tag) =>
    ["degradation", "no_significant_effect", "inconclusive", "contradicted"].includes(tag),
  );
}

function initialView(): GraphView["id"] {
  const value = new URLSearchParams(window.location.search).get("view");
  return viewOrder.includes(value as GraphView["id"])
    ? (value as GraphView["id"])
    : "story";
}

function setDeepLink(node: GraphNode | null, view: GraphView["id"]): void {
  const url = new URL(window.location.href);
  url.searchParams.set("view", view);
  if (node) url.searchParams.set("node", node.id);
  else url.searchParams.delete("node");
  window.history.replaceState({}, "", url);
}

function EffectList({ detail }: { detail: EntityDetail }) {
  const effects = detail.artifact.effects;
  if (!Array.isArray(effects) || effects.length === 0) return null;
  return (
    <section className="drawer-section">
      <p className="eyebrow">Measured effects</p>
      <div className="effect-list">
        {effects.map((effect, index) => {
          if (typeof effect !== "object" || effect === null) return null;
          const record = effect as Record<string, unknown>;
          const relative = typeof record.relative === "number" ? record.relative * 100 : null;
          return (
            <article className="effect" key={`${String(record.metric)}-${index}`}>
              <div>
                <strong>{String(record.metric ?? "Metric")}</strong>
                <span>{relative === null ? "Effect recorded" : `${relative.toFixed(1)}% relative`}</span>
              </div>
              {relative !== null && (
                <div className="effect-track" aria-label={`${relative.toFixed(1)} percent relative`}>
                  <span style={{ width: `${Math.min(100, Math.max(4, Math.abs(relative)))}%` }} />
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

const coreArtifactFields = new Set([
  "$schema",
  "schema_version",
  "kind",
  "id",
  "version",
  "slug",
  "title",
  "description",
  "status",
  "authors",
  "created_at",
  "updated_at",
  "license",
  "citations",
  "provenance",
  "extensions",
]);

const artifactFieldPriority = [
  "question",
  "observation",
  "falsifiable_statement",
  "statement",
  "outcome",
  "selected_configuration",
  "mechanism",
  "expected_mechanism",
  "baseline",
  "candidates",
  "changed_factors",
  "frozen_factors",
  "design",
  "analysis",
  "primary_metric",
  "secondary_metrics",
  "guardrail_metrics",
  "quality_metrics",
  "effects",
  "scope",
  "conditions",
  "boundaries",
  "limitations",
  "caveats",
];

function DetailValue({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null || value === undefined || value === "") {
    return <span className="detail-empty">Not specified</span>;
  }
  if (typeof value === "boolean") {
    return <span className={`boolean-value ${value ? "true" : "false"}`}>{value ? "Yes" : "No"}</span>;
  }
  if (typeof value === "number") {
    return <data className="number-value">{value.toLocaleString()}</data>;
  }
  if (typeof value === "string") {
    if (/^https?:\/\//.test(value)) {
      return (
        <a href={value} target="_blank" rel="noreferrer">
          {value} ↗
        </a>
      );
    }
    if (value.startsWith("atlas://")) return <code>{value}</code>;
    return <span className={value.length > 100 ? "long-value" : undefined}>{value}</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="detail-empty">None recorded</span>;
    const primitives = value.every(
      (item) => item === null || !["object", "function"].includes(typeof item),
    );
    if (primitives) {
      return (
        <ul className="detail-chip-list">
          {value.map((item, index) => (
            <li key={`${String(item)}-${index}`}>
              <DetailValue value={item} depth={depth + 1} />
            </li>
          ))}
        </ul>
      );
    }
    return (
      <div className="detail-object-list">
        {value.map((item, index) => (
          <article key={index}>
            <span className="object-index">{String(index + 1).padStart(2, "0")}</span>
            <DetailValue value={item} depth={depth + 1} />
          </article>
        ))}
      </div>
    );
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <span className="detail-empty">No values recorded</span>;
    return (
      <dl className={`detail-nested depth-${Math.min(depth, 3)}`}>
        {entries.map(([key, nestedValue]) => (
          <div key={key}>
            <dt>{titleCase(key)}</dt>
            <dd>
              <DetailValue value={nestedValue} depth={depth + 1} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return <span>{String(value)}</span>;
}

function ArtifactFields({ detail }: { detail: EntityDetail }) {
  const entries = Object.entries(detail.artifact);
  const specific = entries
    .filter(([key]) => !coreArtifactFields.has(key))
    .sort(([left], [right]) => {
      const leftRank = artifactFieldPriority.indexOf(left);
      const rightRank = artifactFieldPriority.indexOf(right);
      return (leftRank < 0 ? 10_000 : leftRank) - (rightRank < 0 ? 10_000 : rightRank);
    });
  const record = entries.filter(([key]) => coreArtifactFields.has(key));
  return (
    <>
      <section className="drawer-section artifact-details">
        <div className="drawer-section-heading">
          <div>
            <p className="eyebrow">Node-specific details</p>
            <h3>{titleCase(detail.node.type)} record</h3>
          </div>
          <span>{specific.length} fields</span>
        </div>
        <div className="artifact-field-grid">
          {specific.map(([key, value]) => (
            <article
              className={typeof value === "object" && value !== null ? "complex-field" : ""}
              key={key}
            >
              <h4>{titleCase(key)}</h4>
              <DetailValue value={value} />
            </article>
          ))}
        </div>
      </section>
      <section className="drawer-section artifact-details record-details">
        <div className="drawer-section-heading">
          <div>
            <p className="eyebrow">Canonical record</p>
            <h3>Identity and provenance</h3>
          </div>
          <span>{record.length} fields</span>
        </div>
        <div className="artifact-field-grid">
          {record.map(([key, value]) => (
            <article
              className={typeof value === "object" && value !== null ? "complex-field" : ""}
              key={key}
            >
              <h4>{titleCase(key)}</h4>
              <DetailValue value={value} />
            </article>
          ))}
        </div>
      </section>
    </>
  );
}

function RelationDetails({
  title,
  edges,
  direction,
}: {
  title: string;
  edges: EntityDetail["incoming"];
  direction: "incoming" | "outgoing";
}) {
  if (edges.length === 0) return null;
  return (
    <div className="relation-group">
      <h3>{title}</h3>
      {edges.map((edge) => (
        <article className="relation-card" key={edge.id}>
          <div className="relation-card-heading">
            <strong>{relationLabel(edge.relation)}</strong>
            <span>{edge.assertion_level}</span>
          </div>
          <code>{artifactCode(direction === "incoming" ? edge.source : edge.target)}</code>
          <dl>
            <div>
              <dt>Confidence</dt>
              <dd>{edge.confidence}</dd>
            </div>
            <div>
              <dt>Evidence</dt>
              <dd>
                <DetailValue value={edge.evidence} />
              </dd>
            </div>
            <div>
              <dt>Scope</dt>
              <dd>
                <DetailValue value={edge.scope} />
              </dd>
            </div>
            <div>
              <dt>Provenance</dt>
              <dd>
                <DetailValue value={edge.provenance} />
              </dd>
            </div>
          </dl>
        </article>
      ))}
    </div>
  );
}

function EntityDrawer({
  detail,
  loading,
  repositoryRevision,
  onClose,
  onWhy,
}: {
  detail: EntityDetail | null;
  loading: boolean;
  repositoryRevision: string;
  onClose: () => void;
  onWhy: () => void;
}) {
  if (!detail && !loading) return null;
  const revision = repositoryRevision.endsWith("-dirty")
    ? "main"
    : repositoryRevision.slice(0, 40);
  return (
    <aside className="entity-drawer" aria-label="Evidence details" aria-live="polite">
      <button className="drawer-close" onClick={onClose} aria-label="Close details">
        Close ×
      </button>
      {loading || !detail ? (
        <div className="drawer-loading">Resolving evidence…</div>
      ) : (
        <>
          <header className="drawer-identity">
            <div>
              <p className="eyebrow">{titleCase(detail.node.type)}</p>
              <code>{artifactCode(detail.node.artifact_ref)}</code>
            </div>
            <h2>{detail.node.label}</h2>
            <p className="drawer-summary">{detail.node.summary}</p>
            <div className="status-row">
              <span>{detail.node.status}</span>
              <code>{detail.node.artifact_ref}</code>
              {detail.node.study && <code>{artifactCode(detail.node.study)}</code>}
            </div>
          </header>
          {detail.node.type === "decision" && (
            <button className="primary-action" onClick={onWhy}>
              Why this decision?
            </button>
          )}
          <EffectList detail={detail} />
          <ArtifactFields detail={detail} />
          <section className="drawer-section">
            <div className="drawer-section-heading">
              <div>
                <p className="eyebrow">Evidence links</p>
                <h3>Recorded relationships</h3>
              </div>
              <span>{detail.incoming.length + detail.outgoing.length} edges</span>
            </div>
            <dl className="link-stats">
              <div>
                <dt>Incoming</dt>
                <dd>{detail.incoming.length}</dd>
              </div>
              <div>
                <dt>Outgoing</dt>
                <dd>{detail.outgoing.length}</dd>
              </div>
              <div>
                <dt>Referenced by</dt>
                <dd>{detail.referenced_by.length}</dd>
              </div>
            </dl>
            <RelationDetails title="Incoming evidence" edges={detail.incoming} direction="incoming" />
            <RelationDetails title="Outgoing evidence" edges={detail.outgoing} direction="outgoing" />
            {detail.referenced_by.length > 0 && (
              <div className="relation-group referenced-by">
                <h3>Referenced by</h3>
                <DetailValue value={detail.referenced_by} />
              </div>
            )}
          </section>
          {detail.node.type === "source" && (
            <section className="drawer-section">
              <p className="eyebrow">Source record</p>
              {typeof detail.artifact.url === "string" && (
                <a href={detail.artifact.url} target="_blank" rel="noreferrer">
                  Open authoritative source ↗
                </a>
              )}
              <p>{String(detail.artifact.relevance ?? "")}</p>
            </section>
          )}
          <section className="drawer-section provenance">
            <p className="eyebrow">Repository provenance</p>
            <p>The canonical source file for this node is versioned in Git.</p>
            <a
              href={`https://github.com/Ayobami-00/llm-inference-optimization-atlas/blob/${revision}/${detail.node.source_path}`}
              target="_blank"
              rel="noreferrer"
            >
              {detail.node.source_path} ↗
            </a>
          </section>
        </>
      )}
    </aside>
  );
}

export function App() {
  const [atlas, setAtlas] = useState<AtlasData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewId, setViewId] = useState<GraphView["id"]>(initialView);
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [selectedTypes, setSelectedTypes] = useState<Set<string>>(new Set());
  const [showNegative, setShowNegative] = useState(true);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [detail, setDetail] = useState<EntityDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [highlighted, setHighlighted] = useState<Set<string>>(new Set());
  const core = useRef<Core | null>(null);

  useEffect(() => {
    loadAtlas()
      .then((value) => {
        setAtlas(value);
        const requested = new URLSearchParams(window.location.search).get("node");
        const node = value.graph.nodes.find((candidate) => candidate.id === requested);
        if (node) setSelected(node);
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, []);

  useEffect(() => {
    if (!atlas || !selected?.detail_path) {
      setDetail(null);
      return;
    }
    setDetailLoading(true);
    loadEntity(atlas, selected.detail_path)
      .then(setDetail)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setDetailLoading(false));
  }, [atlas, selected]);

  const selectNode = useCallback(
    (node: GraphNode) => {
      setSelected(node);
      setQuery("");
      setSearchOpen(false);
      setHighlighted(new Set());
      setDeepLink(node, viewId);
      window.requestAnimationFrame(() => {
        const element = core.current?.getElementById(node.id);
        if (!element?.length) return;
        core.current?.elements().unselect();
        element.select();
      });
    },
    [viewId],
  );
  const graphReady = useCallback((value: Core) => {
    core.current = value;
  }, []);
  const clearSelection = useCallback(() => {
    setSelected(null);
    setDetail(null);
    setHighlighted(new Set());
    setDeepLink(null, viewId);
  }, [viewId]);

  const changeView = (next: GraphView["id"]) => {
    setViewId(next);
    setSelectedTypes(new Set());
    setHighlighted(new Set());
    setSelected(null);
    setDetail(null);
    setDeepLink(null, next);
  };

  const activeView = atlas?.views[viewId];
  const presentation = activeView?.filters.presentation;
  const typeCounts = useMemo(() => {
    if (!atlas || !activeView) return [];
    const ids = new Set(activeView.node_ids);
    const counts = new Map<string, number>();
    for (const node of atlas.graph.nodes) {
      if (ids.has(node.id)) counts.set(node.type, (counts.get(node.type) ?? 0) + 1);
    }
    const stageRank = new Map<string, number>();
    activeView.filters.presentation?.stages.forEach((stage, stageIndex) => {
      stage.types.forEach((type, typeIndex) => stageRank.set(type, stageIndex * 100 + typeIndex));
    });
    return [...counts.entries()].sort((left, right) => {
      if (stageRank.size > 0) {
        return (stageRank.get(left[0]) ?? 10_000) - (stageRank.get(right[0]) ?? 10_000);
      }
      return right[1] - left[1] || left[0].localeCompare(right[0]);
    });
  }, [activeView, atlas]);

  const matches = useMemo(() => {
    if (!atlas || !activeView) return [];
    const needle = query.trim().toLowerCase();
    const activeIds = new Set(activeView.node_ids);
    const typeRank = new Map<string, number>();
    activeView.filters.presentation?.stages.forEach((stage, stageIndex) => {
      stage.types.forEach((type, typeIndex) => typeRank.set(type, stageIndex * 100 + typeIndex));
    });
    const searchable = (node: GraphNode) =>
      `${artifactCode(node.artifact_ref)} ${node.label} ${node.summary} ${node.type} ${node.tags.join(" ")}`
        .toLowerCase()
        .includes(needle);
    const visible = atlas.graph.nodes
      .filter(
        (node) =>
          activeIds.has(node.id) &&
          (selectedTypes.size === 0 || selectedTypes.has(node.type)) &&
          (showNegative || !isNegativeNode(node)) &&
          (!needle || searchable(node)),
      )
      .sort(
        (left, right) =>
          (typeRank.get(left.type) ?? 10_000) - (typeRank.get(right.type) ?? 10_000) ||
          artifactCode(left.artifact_ref).localeCompare(artifactCode(right.artifact_ref)),
      );
    const elsewhere = needle
      ? atlas.graph.nodes.filter((node) => !activeIds.has(node.id) && searchable(node))
      : [];
    return [
      ...visible.map((node) => ({ node, current: true })),
      ...elsewhere.map((node) => ({ node, current: false })),
    ].slice(0, 12);
  }, [activeView, atlas, query, selectedTypes, showNegative]);

  const toggleType = (type: string) => {
    setSelectedTypes((current) => {
      const next = new Set(current);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  };

  const highlightDecisionPath = (decision = selected) => {
    if (!atlas || !decision) return;
    const included = new Set<string>([decision.id]);
    const allowedIncoming = new Set(["JUSTIFIES", "SUPPORTS", "COMPARES", "PRODUCES"]);
    for (let pass = 0; pass < 4; pass += 1) {
      for (const edge of atlas.graph.edges) {
        if (allowedIncoming.has(edge.relation) && included.has(edge.target)) {
          included.add(edge.id);
          included.add(edge.source);
          included.add(edge.target);
        }
        if (
          edge.source === decision.id &&
          ["USES_CONFIGURATION", "REJECTS"].includes(edge.relation)
        ) {
          included.add(edge.id);
          included.add(edge.target);
        }
      }
    }
    setHighlighted(included);
    core.current?.elements().removeClass("path");
    for (const id of included) core.current?.getElementById(id).addClass("path");
    core.current?.fit(core.current.elements(".path"), 70);
  };

  if (error) {
    return (
      <main className="fatal-state">
        <p className="eyebrow">Atlas could not be loaded</p>
        <h1>The evidence graph is unavailable.</h1>
        <p>{error}</p>
      </main>
    );
  }
  if (!atlas || !activeView) {
    return <main className="loading-state">Compiling the map…</main>;
  }

  const decisionNodes = atlas.graph.nodes.filter(
    (node) => node.type === "decision" && activeView.node_ids.includes(node.id),
  );
  const decisionNode = decisionNodes.length === 1 ? decisionNodes[0] : undefined;
  const narrative =
    viewId === "story" && atlas.manifest.scope.type === "global"
      ? globalStoryNarrative
      : viewNarratives[viewId];

  return (
    <div className="atlas-shell">
      <header className="topbar">
        <a className="brand" href={import.meta.env.BASE_URL} aria-label="Atlas home">
          <strong>LLM optimization Inference Atlas</strong>
        </a>
        <div
          className="search-wrap"
          onFocus={() => setSearchOpen(true)}
          onBlur={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
              setSearchOpen(false);
            }
          }}
        >
          <label htmlFor="atlas-search">Search evidence</label>
          <input
            id="atlas-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setSearchOpen(false);
                event.currentTarget.blur();
              }
            }}
            placeholder="Workloads, bottlenecks, optimizations…"
          />
          {searchOpen && matches.length > 0 && (
            <ul className="search-results">
              <li className="search-result-heading">
                {query.trim() ? "Matching nodes" : `Visible in ${activeView.name}`}
              </li>
              {matches.map(({ node, current }) => (
                <li key={node.id}>
                  <button onClick={() => selectNode(node)}>
                    <span>
                      <code>{artifactCode(node.artifact_ref)}</code>
                      {node.label}
                    </span>
                    <small>
                      {titleCase(node.type)} · {current ? activeView.name : "Atlas"}
                    </small>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="revision-pill">
          <span className="live-dot" />
          schema v{atlas.manifest.graph_version} · {atlas.manifest.repository_commit.slice(0, 7)}
        </div>
      </header>

      <aside className="control-rail" aria-label="Graph controls">
        <div className="rail-intro">
          <p className="eyebrow">Explore by question</p>
          <h1>{activeView.name}</h1>
          <p>{activeView.description}</p>
        </div>
        <nav className="view-nav" aria-label="Graph views">
          {viewOrder.map((id, index) => (
            <button
              key={id}
              className={viewId === id ? "active" : ""}
              onClick={() => changeView(id)}
              aria-current={viewId === id ? "page" : undefined}
            >
              <span>{String(index + 1).padStart(2, "0")}</span>
              {atlas.views[id].name}
            </button>
          ))}
        </nav>
        <div className="filter-block">
          <div className="filter-heading">
            <p className="eyebrow">Entity layers</p>
            {selectedTypes.size > 0 && <button onClick={() => setSelectedTypes(new Set())}>Clear</button>}
          </div>
          <div className="type-filters">
            {typeCounts.map(([type, count]) => (
              <button
                key={type}
                className={selectedTypes.has(type) ? "active" : ""}
                onClick={() => toggleType(type)}
                aria-pressed={selectedTypes.has(type)}
              >
                <i style={{ background: `var(--node-${type}, #8ba096)` }} />
                <span>{titleCase(type)}</span>
                <small>{count}</small>
              </button>
            ))}
          </div>
        </div>
        <label className="negative-toggle">
          <input
            type="checkbox"
            checked={showNegative}
            onChange={(event) => setShowNegative(event.target.checked)}
          />
          <span>Show negative & inconclusive evidence</span>
        </label>
      </aside>

      <main className={`graph-stage ${presentation ? "guided-view" : "exploratory-view"}`}>
        <section className="stage-heading" aria-labelledby="active-view-title">
          <div className="stage-title-block">
            <div className="stage-context">
              <p className="eyebrow">
                {atlas.manifest.scope.type === "global" ? "Global evidence graph" : "Study graph"}
              </p>
              <p>
                <strong>{activeView.node_ids.length}</strong> entities ·{" "}
                <strong>{activeView.edge_ids.length}</strong> explicit relations
              </p>
            </div>
            <h2 className="stage-description" id="active-view-title">
              {activeView.description}
            </h2>
            <div className="view-summary" aria-label={`${activeView.name} view explanation`}>
              {narrative.map((sentence) => (
                <p key={sentence}>{sentence}</p>
              ))}
            </div>
          </div>
          <div className="stage-actions">
            {decisionNode && ["story", "deployment"].includes(viewId) && (
              <button
                className="why-control"
                onClick={() => {
                  selectNode(decisionNode);
                  window.requestAnimationFrame(() => highlightDecisionPath(decisionNode));
                }}
              >
                Why this decision?
              </button>
            )}
            <div className="zoom-controls" aria-label="Zoom controls">
              <button
                onClick={() => core.current?.zoom(core.current.zoom() * 1.2)}
                aria-label="Zoom in"
              >
                +
              </button>
              <button
                onClick={() => {
                  core.current?.fit(undefined, presentation ? 38 : 50);
                }}
                aria-label="Fit graph"
              >
                Fit
              </button>
              <button
                onClick={() => core.current?.zoom(core.current.zoom() / 1.2)}
                aria-label="Zoom out"
              >
                −
              </button>
            </div>
          </div>
          <div className="entity-key" aria-label="Entity color key">
            <span className="key-label">Node key</span>
            <div>
              {typeCounts.map(([type]) => (
                <button
                  key={type}
                  className={selectedTypes.has(type) ? "active" : ""}
                  onClick={() => toggleType(type)}
                  aria-pressed={selectedTypes.has(type)}
                  title={`Show only ${titleCase(type)} entities`}
                >
                  <i style={{ background: `var(--node-${type}, #8ba096)` }} />
                  <code>{entityPrefix(type, atlas.graph.nodes)}</code>
                  <span>{titleCase(type)}</span>
                </button>
              ))}
            </div>
          </div>
          {presentation && (
            <div className="reading-guide" aria-label="Graph reading order">
              <div className="stage-flow">
                <span className="guide-start">Start</span>
                {presentation.stages.map((stage, index) => (
                  <span key={stage.label}>
                    {stage.label}
                    {index < presentation.stages.length - 1 && <i aria-hidden="true">→</i>}
                  </span>
                ))}
              </div>
              <p>{presentation.intro}</p>
            </div>
          )}
        </section>
        <div className="graph-frame">
          <GraphCanvas
            graph={atlas.graph}
            view={activeView}
            query={query}
            selectedTypes={selectedTypes}
            showNegative={showNegative}
            highlighted={highlighted}
            onSelect={selectNode}
            onReady={graphReady}
          />
        </div>
        <footer className="graph-footer">
          {presentation && (
            <div className="relation-legend" aria-label="Relation legend">
              <span>Hover a node to name its links</span>
              {presentation.relations.map((relation) => (
                <span key={relation}>
                  <i
                    className={`relation-${relation.toLowerCase().replaceAll("_", "-")}`}
                    aria-hidden="true"
                  />{" "}
                  {relationLabel(relation)}
                </span>
              ))}
            </div>
          )}
          <div className="canvas-note">
            <span>
              Drag to pan · scroll to zoom · select a circle to open its complete record
            </span>
            <span>Generated {atlas.manifest.generated_at.slice(0, 10)}</span>
          </div>
        </footer>
      </main>

      <EntityDrawer
        detail={detail}
        loading={detailLoading}
        repositoryRevision={atlas.manifest.repository_commit}
        onClose={clearSelection}
        onWhy={highlightDecisionPath}
      />
    </div>
  );
}
