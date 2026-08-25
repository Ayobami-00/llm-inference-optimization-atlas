# Studies

`studies/` contains realistic, versioned uses of the reference contracts. These
are canonical evidence contributions, not disposable examples.

Each study owns its workload, quality and SLO contracts; hypotheses and resolved
configurations; one or more experiments; flexible execution bundles; immutable
accepted runs; comparisons; findings; and deployment decisions.

An execution bundle always includes `run.sh`. It adds `start.sh` and `destroy.sh`
when resources need lifecycle management, and may add `prepare.sh` for explicit
networked artifact preparation. Bundle-specific `src/` and `config/` structures
are intentionally unconstrained beyond the declared manifest and README.

## Bootstrap studies

| Study | Proposal | Experiments | Accepted runs | Findings | Decision |
|---|---|---:|---:|---:|---|
| [S001 CPU interactive chat](S001-cpu-interactive-chat/v1/README.md) | GitHub #2 / P0002 | 4 | 30 | 6 | DEC0001 |
| [S002 CPU coding agent](S002-cpu-coding-agent/v1/README.md) | GitHub #3 / P0003 | 4 | 30 | 6 | DEC0002 |
| [S003 CPU enterprise RAG](S003-cpu-enterprise-rag/v1/README.md) | GitHub #4 / P0004 | 4 | 27 | 5 | DEC0003 |

## Reproduce one study

```bash
uv run atlas execution list S001-cpu-interactive-chat
uv run atlas execution prepare S001-cpu-interactive-chat transformers-cpu
uv run atlas execution run S001-cpu-interactive-chat transformers-cpu --profile quick
```

Drafts stay under `.atlas/work/`. Inspect and validate them before assigning a
new run ID with `atlas evidence promote`. Never replace an accepted run in place.

Build the global and per-study views with:

```bash
uv run atlas graph build --all
uv run atlas site build
uv run atlas graph serve S001-cpu-interactive-chat
```

See [the reproduction guide](../docs/guides/reproduce-a-study.md) for the full
prepare/run/validate/promote/compare sequence and safety boundaries.
