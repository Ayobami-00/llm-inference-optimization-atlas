# V1 quality-evaluation protocol

Performance evidence is eligible only when the candidate satisfies the quality contract fixed before
results are inspected. Quality is a vector of workload-specific dimensions, never an undocumented
single score.

## Gate hierarchy

### Q0 — integrity and correctness

Required for every run. Check process outcome, API shape, tokenizer/model compatibility, malformed or
empty output, finite measurements, request accounting, deterministic invariants, and obvious task
correctness. Any Q0 failure makes the run ineligible for findings.

### Q1 — compact regression suite

Use a repository-owned or clearly licensed representative subset. It should cover common classes,
known edge cases, output formatting, and task-specific correctness. Thresholds include both absolute
minimums and allowed regression from the registered reference configuration.

### Q2 — full evaluation

Use after lossy or model-transforming work and whenever Q1 lacks sensitivity to the expected failure
mode. Q2 may combine automated metrics, model-based judging, human evaluation, safety checks, and
domain-specific tests. Record judge identity/revision, prompt, decoding, calibration, and agreement.

## Contract design

For each dimension record dataset, evaluator, metric, direction, aggregation, threshold, allowed
regression, request classes, missing-result behavior, and uncertainty method. Freeze the reference
configuration and thresholds before candidate results.

Examples include exact-match correctness, unit-test pass rate, retrieval recall, groundedness,
citation correctness, answer completeness, refusal behavior, format validity, and semantic similarity.
Proxy metrics must be labeled and cannot silently stand in for product quality.

## Pairing and nondeterminism

Use identical inputs and seeds for controlled comparisons. If decoding or the runtime is nondeterministic,
use repeated samples or task-level paired analysis. Record temperature, top-p/top-k, sampling library,
seed handling, stop sequences, and maximum output length.

## Missing and failed results

The contract states whether timeout, refusal, malformed output, execution error, or missing judge result
scores as failure, receives a bounded penalty, or makes the run invalid. Never drop these rows before
aggregation. Report numerator and denominator.

## Generated code

Code quality is evaluated in an ephemeral sandbox with no network, non-root execution, read-only root
filesystem, tmpfs workspace, CPU/memory/PID limits, and hard timeouts. Tests are repository-owned and
model output is treated as untrusted input.

## Reporting

Publish per-dimension counts and aggregate results, reference/candidate deltas, confidence intervals
where meaningful, gate outcome, and failed examples safe to redistribute. Passing Q1 does not imply
semantic equivalence; it means the candidate met the predeclared compact contract.

Benchmark records such as `atlas://source/SRC0092@v1`, `atlas://source/SRC0093@v1`, and
`atlas://source/SRC0096@v1` provide evaluation context, not Atlas evidence.
