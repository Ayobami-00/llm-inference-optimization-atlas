# Explore global and per-study graphs

Build the same static explorer used by GitHub Pages:

```bash
uv run atlas site build
uv run atlas graph serve
```

The homepage opens the Story view. Use the left navigation to switch to
Bottleneck, Optimization, Evidence, Deployment, or All. Entity filters operate
within the current view. Search spans the loaded graph, including external source
records that are intentionally hidden from Story.

Selecting a node opens its evidence drawer with status, measured effects,
incoming and outgoing relations, reverse source references, and a link to the
canonical repository path at the compiled revision. Selecting a decision enables
“Why this decision?” path highlighting through its findings, comparisons, and
supporting evidence.

The negative/inconclusive toggle hides or restores those results without deleting
them. The URL preserves `view` and selected `node`, so a reviewer can share a deep
link to the same state.

Serve one study directly with:

```bash
uv run atlas graph serve S003-cpu-enterprise-rag
```

Stable paths are `/studies/<directory-slug>/v1/`. The route loads the per-study
manifest and views while using the identical frontend bundle as the global Atlas.
Every view file is a subset of the canonical study graph; there is no hand-edited
presentation graph.
