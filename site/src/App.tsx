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
  "all",
];

function titleCase(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function relationLabel(value: string): string {
  if (value === "USES_CONFIGURATION") return "selects / uses";
  return value.replaceAll("_", " ").toLowerCase();
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
          <p className="eyebrow">{titleCase(detail.node.type)}</p>
          <h2>{detail.node.label}</h2>
          <p className="drawer-summary">{detail.node.summary}</p>
          <div className="status-row">
            <span>{detail.node.status}</span>
            <code>{detail.node.artifact_ref.split("/").at(-1)}</code>
          </div>
          {detail.node.type === "decision" && (
            <button className="primary-action" onClick={onWhy}>
              Why this decision?
            </button>
          )}
          <EffectList detail={detail} />
          <section className="drawer-section">
            <p className="eyebrow">Evidence links</p>
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
            <ul className="relation-list">
              {[...detail.incoming, ...detail.outgoing].slice(0, 12).map((edge) => (
                <li key={edge.id}>
                  <span>{edge.relation.replaceAll("_", " ")}</span>
                  <small>{edge.assertion_level}</small>
                </li>
              ))}
            </ul>
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
      setHighlighted(new Set());
      setDeepLink(node, viewId);
      window.requestAnimationFrame(() => {
        const element = core.current?.getElementById(node.id);
        if (!element?.length) return;
        core.current?.elements().unselect();
        element.select();
        core.current?.center(element);
      });
    },
    [viewId],
  );
  const graphReady = useCallback((value: Core) => {
    core.current = value;
  }, []);

  const changeView = (next: GraphView["id"]) => {
    setViewId(next);
    setSelectedTypes(new Set());
    setHighlighted(new Set());
    setDeepLink(selected, next);
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
    return [...counts.entries()].sort((left, right) => right[1] - left[1]);
  }, [activeView, atlas]);

  const matches = useMemo(() => {
    if (!atlas || !query.trim()) return [];
    const needle = query.toLowerCase();
    return atlas.graph.nodes
      .filter((node) => `${node.label} ${node.summary}`.toLowerCase().includes(needle))
      .slice(0, 8);
  }, [atlas, query]);

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

  return (
    <div className="atlas-shell">
      <header className="topbar">
        <a className="brand" href={import.meta.env.BASE_URL} aria-label="Atlas home">
          <span className="brand-mark">A</span>
          <span>
            <strong>LLM optimizations Inference Atlas</strong>
            <small>Evidence before intuition</small>
          </span>
        </a>
        <div className="search-wrap">
          <label htmlFor="atlas-search">Search evidence</label>
          <input
            id="atlas-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Workloads, bottlenecks, optimizations…"
          />
          {matches.length > 0 && (
            <ul className="search-results">
              {matches.map((node) => (
                <li key={node.id}>
                  <button onClick={() => selectNode(node)}>
                    <span>{node.label}</span>
                    <small>{titleCase(node.type)}</small>
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

      <main className="graph-stage">
        <div className="stage-heading">
          <div>
            <div className="stage-context">
              <p className="eyebrow">
                {atlas.manifest.scope.type === "global" ? "Global evidence graph" : "Study graph"}
              </p>
              <p>
                <strong>{activeView.node_ids.length}</strong> entities ·{" "}
                <strong>{activeView.edge_ids.length}</strong> explicit relations
              </p>
            </div>
            <h2 className="stage-description">{activeView.description}</h2>
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
        {presentation && (
          <div className="relation-legend" aria-label="Relation legend">
            <span>Hover a card to name its links</span>
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
          <span>Drag to pan · scroll to zoom · select an entity to inspect evidence</span>
          <span>Generated {atlas.manifest.generated_at.slice(0, 10)}</span>
        </div>
      </main>

      <EntityDrawer
        detail={detail}
        loading={detailLoading}
        repositoryRevision={atlas.manifest.repository_commit}
        onClose={() => {
          setSelected(null);
          setDetail(null);
          setHighlighted(new Set());
          setDeepLink(null, viewId);
        }}
        onWhy={highlightDecisionPath}
      />
    </div>
  );
}
