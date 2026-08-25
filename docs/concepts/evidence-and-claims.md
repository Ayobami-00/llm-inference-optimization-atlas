# Evidence, claims, confidence, and transferability

The Atlas distinguishes a measurement from an interpretation and an exact result
from a transferable recommendation.

## Evidence chain

A run is accepted only when its configuration, environment snapshot, inputs,
commands, windows, outputs, quality results, Parquet column contracts, and file
checksums validate. Failed attempts remain drafts and cannot support findings.

A comparison selects compatible accepted baseline and candidate runs, pairs common
seeds when possible, identifies deliberately changed axes, and reports absolute
and relative effects with confidence intervals. V1 uses 10,000 paired bootstrap
resamples when appropriate. Three independent replicates are the minimum for an
accepted comparison.

A finding states the observed effect and proposed mechanism, then records where
it works, where it may stop, interactions, limitations, evidence confidence, and
transferability. A decision evaluates the Pareto envelope, names rejected
alternatives, and can legitimately produce `no_recommendation`.

## Quality and SLO eligibility

Q0 checks execution correctness, crashes, malformed output, APIs, and tokenizers.
Q1 runs a compact workload-specific regression suite. Q2 is the full evaluation
required after lossy or model-changing interventions. Thresholds and allowed
regressions are fixed before candidate results.

An effect may be measurable but ineligible because quality or SLO constraints
failed. The graph preserves that evidence but cannot present it as an eligible
deployment improvement.

## Result and claim status

Comparisons distinguish improvement, degradation, no significant effect, mixed,
and invalid results. No-effect means the interval did not resolve a directional
effect under this design; it does not prove equality.

Findings distinguish proposed, reviewed, supported, inconclusive, contradicted,
superseded, and generalized claims. Negative and inconclusive findings remain
first-class graph entities.

## Two independent confidence axes

`evidence_confidence` describes confidence in the exact measured setup. It grows
with integrity, control, replicate agreement, measurement quality, and mechanism
validation.

`transferability` describes how far the result has actually been tested:
exact setup, same hardware class, cross-hardware, cross-runtime, cross-model, or
cross-workload. High exact-setup confidence does not imply broad transferability.
Only explicit replication can expand that boundary.
