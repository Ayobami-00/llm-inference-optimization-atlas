# V1 graph semantics protocol

## Purpose

The evidence graph is a deterministic projection of canonical repository artifacts. It is an index and
explanation surface, not a second database and not an independent source of truth.

## Nodes

Nodes represent workloads, characteristics, traffic regimes, studies, quality contracts, SLOs, models,
hardware, runtimes, configurations, bottlenecks, optimizations, hypotheses, experiments, runs,
comparisons, findings, decisions, replications, and external sources. Node identity is the canonical
`atlas://<kind>/<ID>@v<version>` reference.

## Edges

Every edge records source, target, relation, assertion level, evidence references, scope, confidence, and
provenance. Structural edges are derived from explicit references. Claim-bearing edges must point to the
comparison/finding that justifies them. Reverse source indexes are generated; source records never store
manual `referenced_by` lists.

## Assertion guardrails

- `ASSOCIATED_WITH` may represent observational correlation.
- `HYPOTHESIZED_TO_CAUSE` is preregistered expectation.
- `VALIDATED_AS_BOTTLENECK` requires controlled or disambiguating Atlas evidence.
- `IMPROVES`, `DEGRADES`, and `NO_SIGNIFICANT_EFFECT` require eligible comparisons.
- `SUPPORTS` and `CONTRADICTS` connect evidence to a finding, not a source to an Atlas claim.
- `REPLICATES` requires a replication artifact.

The compiler never upgrades assertion level based on relation name alone. External-source `CITES` edges
are theoretical context even when the cited paper reports an experiment.

## Scope and confidence

Edges carry machine-readable scope dimensions and exact-setup confidence. Transferability remains an
attribute of findings/replications and is not inferred from node degree. Conflicting edges coexist and
are visible by status and evidence date.

## Views

- Story: workload-to-decision narrative; sources hidden by default.
- Bottleneck: symptoms, diagnostics, causes, and candidate interventions.
- Optimization: mechanisms, requirements, conflicts, evidence, and boundaries.
- Evidence: experiments, runs, comparisons, findings, and replications.
- Deployment: decision rationale, supporting paths, alternatives, and constraints.
- All: complete graph including sources and superseded/invalidated artifacts.

Views are subsets of one canonical graph. No view may invent nodes or edges. Search indexes and entity
detail documents are generated deterministically.

## Provenance and determinism

Each generated object stores canonical repository path, artifact digest, schema version, graph compiler
version, and repository revision. Serialization uses stable sorting and normalized JSON. Two builds from
the same canonical tree must be byte-identical except for fields explicitly designated non-deterministic;
V1 designates none.

Cytoscape.js presentation is grounded by `atlas://source/SRC0077@v1`.
