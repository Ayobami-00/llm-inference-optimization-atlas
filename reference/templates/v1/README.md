# V1 templates

- `study/`: study metadata plus workload, quality, SLO, input, and execution scaffolds.
- `experiment/`: controlled experiment, hypothesis, runtime, and resolved configuration scaffolds.
- `execution-bundle/`: unconstrained implementation code behind a small lifecycle interface.
- `finding/`: evidence-scoped claim skeleton.
- `decision/`: deployment decision, including no-recommendation outcomes.
- `proposals/`: contribution proposals reviewed before implementation.

Execution implementations may use any language or internal layout. The stable interface is
`execution.yaml`, `README.md`, `run.sh`, and, when needed, `start.sh` and `destroy.sh`.
