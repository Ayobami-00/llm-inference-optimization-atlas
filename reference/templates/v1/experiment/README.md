# Experiment scaffold

An experiment changes a declared factor between resolved configurations. Keep pilot execution in
`.atlas/work`; promote only validated evidence. Store accepted runs beneath
`experiments/E####/runs/R####/` and comparisons beneath `experiments/E####/comparisons/`.

Comparison effects default to the primary metrics. To generate effects for selected secondary or
guardrail metrics too, add an ordered `analysis.effect_metrics` list containing every primary metric
and only metrics already declared by the experiment.
