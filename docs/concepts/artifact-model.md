# Artifact identity and versioning

Every canonical artifact carries `$schema`, `schema_version`, `kind`, `id`,
`version`, `slug`, title and description, status, authors, timestamps, license,
citations, provenance, and namespaced extensions.

The stable reference form is:

```text
atlas://<kind>/<ID>@v<version>
```

Examples are `atlas://study/S003@v1`, `atlas://run/R3411@v1`, and
`atlas://source/SRC0002@v1`. Directory slugs aid navigation but do not replace the
canonical identity. File moves therefore do not break references.

## Identity families

`SRC####` identifies external sources; `W###` workloads; `T###` traffic;
`S###` studies; `QC###` quality contracts; `SLO###` SLO profiles; `M###` model
revisions; `HW###` hardware; `RT###` runtimes; `CFG###` resolved configurations;
`B###` bottlenecks; `OPT###` optimizations; `HYP###` hypotheses; `E####`
experiments; `R####` runs; `CMP####` comparisons; `F####` findings; `DEC####`
decisions; `REP####` replications; and `P####` proposals.

## What a version means

Schema path `v1` identifies a contract generation. Artifact `version: 1`
identifies a specific canonical object version. The source registry’s `v1`
directory describes the source-record format, not a frozen list of publications.
New sources and ontology entries can be added without introducing V2.

Changing spelling or explanatory prose may update a record in review. Changing a
fact that affects reproducibility—model bytes, tokenizer, runtime commit, hardware
topology, workload fingerprint, metric semantics, or accepted measurement—requires
a new identity/version or an explicit correction object.

## Closed core, open extension boundary

Schemas reject unknown top-level fields. Project-specific metadata belongs under
a namespaced extension such as `extensions.atlas.condition`. An extension cannot
override core meaning, weaken validation, or carry evidence required to understand
a claim.
