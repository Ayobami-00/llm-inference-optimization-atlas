# Repository and data flow

The Atlas separates definitions, reusable identities, measured evidence, and
generated projections so each layer can evolve without confusing prior research
with current documentation.

```text
reference schemas + ontology + protocols + sources + templates
                              |
                              v
                  registry reusable identities
                              |
                              v
proposal -> study -> experiment -> draft run -> accepted run
                              |
                              v
             comparison -> finding -> decision
                              |
                              v
          generated graph + indexes + static explorer
```

## Canonical layers

`reference/schemas/v1` is the machine contract. JSON Schema Draft 2020-12 is
canonical; YAML is the normal authoring form. Core objects reject unknown fields
with `unevaluatedProperties: false`. Deliberately non-core data goes under
namespaced `extensions` keys.

`reference/ontology/v1` assigns stable IDs and semantics to workload types,
traffic, lifecycle phases, quality gates, hardware classes, bottlenecks,
optimization techniques, metrics, graph relations, and statuses. It is a shared
language, not evidence that an optimization works.

`reference/protocols/v1` defines how evidence must be produced and reviewed.
`reference/sources/v1` records authoritative external material used by protocols,
ontology entries, hypotheses, and registry facts. Source records are passive;
referencing artifacts own `CITES` relationships.

`registry/` stores exact reusable identities: a dataset fixture, evaluator,
immutable model revision, redacted hardware topology, or pinned runtime build.
Changing a reproducibility-relevant fact creates a new version or identity.

`studies/` stores Atlas evidence. A configuration resolves
`E = (W, Q, S, M, H, R, C)` and records hashes of all referenced components.
Experiments preregister the changed and frozen factors. Runs capture raw compact
measurements and provenance; comparisons calculate effects; findings interpret
those effects within scope; decisions select or reject configurations.

## Draft and generated state

`.atlas/cache/` contains recoverable downloaded artifacts and tool caches.
`.atlas/work/` contains draft, failed, quick-profile, and pre-promotion evidence.
Both are ignored. Validation may read them but never downloads models.

`build/` contains reproducible source catalogs, BibTeX, graph projections, search
indexes, entity details, and the static site. Generated files are never canonical
and are ignored by Git.

## Change boundaries

- Before the first V1 release tag, V1 contracts may be refined with fixtures and
  migration review.
- After `v1.0.0`, a contract-breaking schema change starts `schemas/v2`.
- Adding an ontology or source entry does not change the V1 file format.
- Accepted evidence is immutable; corrections use `supersedes` or `invalidates`.
- A finding cannot exceed the scope or metrics of its supporting comparison.
- A decision normally cites Atlas findings, not external benchmark claims.
