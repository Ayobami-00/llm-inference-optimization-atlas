# Add or evolve an external source

The external source registry records papers, official documentation, dataset or
benchmark documentation, standards, and hardware/vendor specifications used by
the Atlas reference system. It does not record Atlas measurements.

## When to add a source

Do not add a source merely because a study reuses an existing ontology concept.
Add one when the same contribution introduces a new externally grounded
definition, mechanism, protocol rule, or registry fact.

Choose the appropriate directory under `reference/sources/v1` and assign the next
reviewed `SRC####` identity. Record title, authors or organization, publisher or
venue, date, DOI/arXiv/official URL, upstream product version or revision when
applicable, retrieval date, topics, a short relevance note, status, and license
metadata required by the source schema.

## Own the relationship at the reference site

The source record must not maintain a manual `supports` list. Instead:

- ontology entries cite sources for definitions and expected mechanisms;
- protocols cite methodological foundations;
- registry records cite official model/runtime/hardware/dataset facts;
- hypotheses cite prior work;
- findings may cite mechanism sources, while comparisons and runs remain the
  only support for measured Atlas claims.

The graph compiler generates reverse “Referenced by” indexes.

## Validate and evolve

```bash
uv run atlas sources check --build
uv run atlas ids check
uv run atlas validate --all --strict
```

Maintainers review authority, relevance, identity duplication, linkage accuracy,
and upstream version specificity. If a source is superseded or retracted, retain
the record, change its status, and link its replacement. Do not delete historical
context. Generated `build/sources/catalog.json` and `bibliography.bib` are
reproducible projections and must not be committed.
