# Amendment 003: cost-constrained single-block publication

## Status and timing

This is a transparent post-data scope reduction, not a prospective statistical
amendment. The investigator approved it on 2026-09-11 after the accepted CFG021
device run and interim, non-final CFG022 host-sync measurements had been
inspected, but before CFG022 became candidate-complete and before CFG023
host-prefetch produced any correctness or performance measurement.

The original preregistration called for five independently initialized paired
blocks. That remains the historical confirmatory design. Compute cost made the
remaining four blocks impractical for this release-day study, so public
execution stops after the first complete paired block: CFG021, CFG022, and
CFG023 with seed 41001.

## Consequences for analysis

- The independent experimental unit remains a separately initialized
  configuration run.
- Each contrast has one paired block and therefore cannot estimate run-to-run
  variance.
- Request count is not substituted for independent replication.
- Pairwise values, absolute effects, relative effects, workload-cell matrices,
  and SLO observations are descriptive for the exact tested system.
- Any mechanically generated single-pair bootstrap interval is degenerate and
  is not interpreted as an uncertainty interval or evidence of statistical
  significance.
- Findings must be labelled exploratory or inconclusive. They cannot support a
  general deployment recommendation.
- A decision may describe the observed trade-off for this exact environment,
  but must remain provisional or `no_recommendation`.

## Evidence and future continuation

All three block-1 configurations retain the original model, runtime, hardware,
workload, seed, measurement windows, quality gate, invalidation policy, and
configuration order. No result, request, workload cell, or metric is removed
because of this amendment.

The unexecuted blocks are recorded as not run because of compute cost, not as
failed or invalid attempts. A future funded extension may execute the remaining
preregistered blocks, but it must identify this public single-block analysis as
already observed and report the additional replication as a staged extension.
Its purpose would be to estimate run-to-run variability, test reproducibility,
and determine whether a deployment recommendation is justified.
