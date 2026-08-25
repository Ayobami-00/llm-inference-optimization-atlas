# V1 study lifecycle

A study progresses through seventeen explicit phases. Lifecycle status is descriptive; acceptance
depends on validation and review, not merely reaching the final phase.

| Phase | Name | Required output | Exit condition |
|---|---|---|---|
| 0 | Intake | Proposal | Scope and contributor intent are legible. |
| 1 | Approval | Approval record | Maintainer applies `proposal:approved`. |
| 2 | Scoping | Study boundaries | Inclusions, exclusions, risks, and resources are fixed. |
| 3 | Workload definition | Workload spec | Semantics, shapes, traffic, state, and fingerprints are defined. |
| 4 | Quality contract | Quality contract | Q0/Q1/Q2 evaluators and thresholds are frozen. |
| 5 | SLO definition | SLO profile | Latency, error, and goodput rules are frozen. |
| 6 | Environment resolution | Registry references | Model, hardware, runtime, and dataset revisions resolve. |
| 7 | Baseline establishment | B0/B1 runs | Baselines pass required quality and integrity checks. |
| 8 | Bottleneck diagnosis | Diagnostic record | Measurements distinguish plausible limiting resources. |
| 9 | Hypothesis registration | Hypothesis | Mechanism, metric, guardrails, and falsification are fixed. |
| 10 | Experiment design | Experiment | Changed/frozen factors, order, seeds, and analysis are fixed. |
| 11 | Pilot | Draft runs | Instrumentation and feasibility are checked; pilot data is labeled. |
| 12 | Execution | Run records | Planned independent replicates complete or failures are retained. |
| 13 | Comparison | Comparison | Compatibility, effects, CIs, quality, and SLO eligibility resolve. |
| 14 | Interpretation | Finding | Claim scope does not exceed evidence scope. |
| 15 | Decision | Decision | Selection, rejection, or no-recommendation is justified. |
| 16 | Publication and maintenance | Graph + docs | CI passes; evidence is reviewable and correction paths exist. |

## State transitions

- `draft` artifacts can be replaced while under review.
- `proposed` artifacts have an associated proposal but are not accepted evidence.
- `approved` means planned work is authorized; it is not a scientific endorsement.
- `running` describes active execution.
- `preliminary` evidence may be useful but cannot support an accepted deployment decision.
- `accepted` evidence passed methodological and integrity review.
- `superseded` and `invalidated` remain discoverable and graphable.

Skipping a phase requires a written deviation in the study. A replication may reuse prior contracts
but must state which artifacts are inherited and whether any transfer axis changes their validity.

## Gate ownership

Study maintainers own design completeness. Evidence reviewers verify measurements and checksums.
Interpretation reviewers verify claim scope and causal language. A person may fill more than one role,
but conflicts must be declared and high-impact findings should receive independent review.

## Reopening

A completed study may gain a new version when its design evolves. New experiments that fit existing
boundaries can be added within the study version. Material changes to workload semantics, quality
contract, or research boundaries require a new study version or a separately approved study.
