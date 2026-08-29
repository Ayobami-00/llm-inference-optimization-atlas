# S001 — CPU interactive chat

This study runs SmolLM2-135M-Instruct through native Transformers/PyTorch CPU on
the redacted Apple M3 topology `HW001`. Twelve repository-owned multi-turn
conversations exercise cold/warm state, batches 1/2/4, thread budgets 1/4/8, and
steady versus bursty request traces.

The full profile produced 30 accepted runs, six comparisons, six findings, and
decision `DEC0001`. For this exact low-concurrency fixture, the selected
configuration is warm batch-one execution with one inference thread. Larger
batches reduced SLO goodput, and the four-request burst exceeded the measured
single-process service envelope.

```bash
uv run atlas execution prepare S001-cpu-interactive-chat transformers-cpu
uv run atlas execution run S001-cpu-interactive-chat transformers-cpu --profile quick
uv run atlas graph build S001-cpu-interactive-chat
uv run atlas graph serve S001-cpu-interactive-chat
```

The compact keyword Q1 gate is a regression fixture, not a claim of broad chat
quality. Queue delay in the burst experiment is modeled from measured service
time rather than captured from a production network server.
