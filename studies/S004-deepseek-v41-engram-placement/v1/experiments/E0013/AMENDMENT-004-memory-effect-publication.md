# Amendment 004: memory and readiness effects in native comparisons

## Status and timing

This is a transparent post-data publication-contract correction recorded at
2026-09-11T01:29:51Z. At that point R3464 and R3465 were accepted and their
summaries had been inspected. CFG023 was still executing its controlled matrix;
no CFG023 candidate, three-way comparison, finding, or decision existed.

Amendment 002 made the scoped latency and throughput effects machine-readable,
but its ordered `analysis.effect_metrics` list accidentally omitted four
already-declared mechanism metrics that the approved proposal and study design
require the native Atlas comparison to expose: available KV-token capacity,
server readiness latency, host memory used, and device memory used.

## Correction

The comparison-effect plan now contains, in order:

1. SLO-qualified offered-load capacity (`MET099`), still the sole primary
   endpoint;
2. available KV-cache token capacity (`MET097`);
3. server readiness latency (`MET098`);
4. TTFT, TPOT, ITL, and output-token throughput (`MET010`, `MET013`, `MET014`,
   and `MET019`); and
5. host and device memory used (`MET053` and `MET058`).

This correction does not change a treatment, request, trace, measurement,
threshold, scope, summary value, primary endpoint, or decision rule. It only
causes already-collected, already-declared run metrics to appear as direct
effects in each native comparison.

## Interpretation constraint

Because the correction was discovered after two configurations had been
observed, these additional effects cannot be presented as a prospective test.
Under Amendment 003 every effect is descriptive for the exact single-block
setup and has no run-to-run confidence interval. `MET099` remains the only
primary endpoint, and this amendment cannot change a comparison or finding from
inconclusive to supported.
