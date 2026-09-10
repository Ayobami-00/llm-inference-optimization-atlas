# Preregistration amendment 002: comparison endpoints and capacity metadata

Status: recorded prospectively on 2026-09-10 at 23:31:35 UTC under the approved
study plan, before the first valid candidate completed and before any
confirmatory capacity search began.

## Why this amendment exists

The frozen study plan requires native Atlas context-by-concurrency effect views
for latency and throughput alongside the primary SLO-capacity comparison. The
initial experiment already declared those metrics and its exact canonical
breakdown scopes, but Atlas generated comparison effects only for primary
metrics. Because `MET099` is the sole primary metric and has no scoped
breakdown, the current comparison generator would retain the overall capacity
effect but omit the preregistered matrix views.

The initial S004 summary also recorded the capacity points, boundary status,
and `MET099` value without separate machine-readable flags for whether any
tested rate passed the SLO and whether a censored boundary remained eligible
for reporting. The legacy comparison fallback interprets only `slo_passed`, so
an absent flag would incorrectly mark every S004 comparison ineligible.

These are publication-contract gaps. They do not change a request, treatment,
measurement, threshold, or numeric estimand.

## Prospective policy

- The experiment freezes this ordered comparison-effect plan:
  `MET099`, `MET010`, `MET013`, `MET014`, and `MET019`.
- `MET099` remains the only primary metric and the only metric that determines
  the overall comparison result. The additional TTFT, TPOT, ITL, and output
  throughput effects are mechanism analyses; scoped effects remain exploratory
  unless the hypothesis names them.
- Comparisons record the ordered effect plan in their method metadata. Exact
  canonical scopes must match across every paired run; missing, duplicate, or
  cross-matched cells remain errors.
- `slo_passed` is true only when at least one tested offered rate satisfies
  every preregistered class SLO and request-quality constraint.
- `slo_eligible` is true for resolved, right-censored, or left-censored
  capacity searches and false for an unresolved search. Right-censored results
  are lower bounds. A left-censored `MET099: 0` means no qualifying rate in the
  declared tested domain; it is not an estimate of zero physical capacity.
- The two flags and the boundary interpretation are derived deterministically
  from retained capacity points and search metadata. They are not hand-edited.
- Before promotion, the finalizer verifies the complete existing draft checksum
  manifest, derives the metadata, records its policy and implementation
  fingerprint, and reseals the mutable `R0000` draft. It refuses allocated or
  tampered evidence. Accepted runs remain immutable.
- Existing Atlas evidence without an explicit `slo_eligible` field retains the
  legacy `slo_passed` interpretation.

## Temporal boundary and treatment of existing attempts

At the time this clarification was recorded, the new
`block-1-CFG021-retry-2` attempt was still executing the controlled performance
matrix. It had not begun its capacity search and had not produced a candidate
run. No S004 run had been accepted and no between-configuration result existed.
The clarification was prompted by a code-path audit, not by a measured effect.

The two earlier CFG021 attempts remain invalid under amendment 001. Nothing in
this amendment reclassifies, promotes, or analyzes them.

## Unchanged design

This amendment does not change the model, hardware, runtime configurations,
request traces, configuration order, seeds, replicate count, warm-up or
measurement windows, correctness gate, SLO thresholds, capacity-search
algorithm, bootstrap procedure, stopping rules, decision thresholds, or
failure policy. It makes the already approved analysis and presentation plan
machine-readable and prevents valid censored capacity evidence from being
silently mislabeled during publication.
