# LLM Inference Optimization Atlas

A community-driven empirical atlas of LLM inference optimization.

The project records reproducible experiments across realistic workloads, models,
hardware, runtimes, and serving configurations to answer a practical question:

> Given a workload, quality contract, SLO, model, and hardware topology, which
> inference configuration should be deployed, when does it work, and why?

The repository is the source of truth. Schemas define the contracts, studies
contain evidence, and a compiler materializes that evidence into an interactive
graph.

```text
Workload -> Hypothesis -> Experiment -> Run -> Comparison
         -> Finding -> Decision -> Evidence Graph
```

## Project status

V1 is under active construction. The initial release will include six workload
archetypes, a comprehensive inference-optimization ontology, reproducibility
protocols, a validation and graph CLI, and three small real-model CPU studies.

## Repository map

- `reference/`: schemas, ontology, protocols, sources, and reusable templates.
- `registry/`: reusable datasets, evaluators, model revisions, hardware, and runtimes.
- `studies/`: versioned empirical studies and accepted evidence.
- `src/atlas/`: validation, execution, comparison, and graph compiler.
- `site/`: static interactive Atlas application.
- `docs/`: architecture, concepts, and contributor guides.

## Development

Requirements are Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js, and npm.

```bash
make setup
make check
```

The core environment never downloads model weights. Real-model study assets are
prepared explicitly through the study execution commands.

## Research principles

- Evidence over anecdotes.
- Quality-constrained performance rather than unqualified throughput.
- Explicit workloads, SLOs, configurations, units, and provenance.
- Negative and inconclusive results are retained.
- External sources explain concepts but never substitute for Atlas evidence.
- Findings remain scoped to the systems actually tested.

See [CONTRIBUTING.md](CONTRIBUTING.md) before proposing a study or experiment.

## License

Apache License 2.0. Individual external datasets and model artifacts retain their
own licenses and are not redistributed unless their terms explicitly permit it.
