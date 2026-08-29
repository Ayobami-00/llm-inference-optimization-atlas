# Evidence graph compilation

The graph is a deterministic projection of canonical files, not a second database.
Deleting `build/atlas` and compiling the same revision must reproduce equivalent
JSON and the same canonical node/edge identities.

## Compiler stages

1. Validate schemas and required protocol invariants.
2. Discover canonical artifacts while excluding `.atlas`, `build`, and caches.
3. Build the global `(kind, id, version)` index.
4. Resolve every `atlas://<kind>/<ID>@v<version>` reference.
5. Check ontology IDs and external source references.
6. Check run/comparison compatibility and finding evidence scope.
7. Reject unsupported causal assertions.
8. Generate the canonical graph, reverse indexes, entity details, and views.
9. Serialize keys and collections deterministically.

Each node records its artifact reference, type, label, status, summary, repository
path, and detail path. Each edge records relation, assertion level, evidence,
scope, confidence, provenance, source, and target.

## Assertion levels

- `structural`: containment, identity, or declared use.
- `theoretical`: mechanism grounded in external sources.
- `hypothetical`: a preregistered falsifiable expectation.
- `observational`: measured association without intervention support.
- `experimentally_supported`: a controlled accepted comparison.
- `replicated`: agreement across declared transfer axes.

`HYPOTHESIZED_TO_CAUSE` does not become a causal edge merely because a metric
moved. Supported effects use explicit `IMPROVES`, `DEGRADES`, or
`NO_SIGNIFICANT_EFFECT` edges backed by comparison and run references.

## Views

- Story follows workload through experiment, evidence, finding, and decision.
- Bottleneck connects pressure, diagnosis, and candidate interventions.
- Optimization centers techniques, requirements, conflicts, and evidence.
- Evidence exposes experiments, runs, comparisons, and claim support.
- Deployment exposes decisions, rejected alternatives, and “Why?” paths.
- All exposes the complete canonical projection, including source records.

Sources are intentionally absent from the default Story view. They remain
available through details, search, source-focused paths, and compiler-generated
“Referenced by” indexes.

Global output is written beneath `build/atlas/`. Every study also receives
`build/atlas/studies/<study>/v1/` with the same manifest, graph, indexes, entity
details, and six view files. The site copies those projections to stable routes.
