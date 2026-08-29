# V1 statistical protocol

## Experimental unit

Define the independent unit before analysis: normally a separately initialized run/replicate, not each
request within one run. Requests are often correlated by shared queues, caches, hardware state, and
time. Request-level pairing improves effect estimation but does not create independent system
replicates.

## Default design

- Use at least three independent replicates for accepted findings.
- Reuse identical traces and seeds for controlled comparisons.
- Randomize candidate order within replicate blocks.
- Use A-B-A or interleaved blocks for important drift-sensitive comparisons.
- Exclude declared warm-up, never post-hoc inconvenient intervals.
- Preserve all outcomes and predeclare stopping/failure rules.

Three replicates are a minimum integrity floor, not a guarantee of precision. Wide intervals produce an
inconclusive finding or motivate more replicates.

## Descriptive statistics

Always report count, mean, p50, p90, and p95 for core latency metrics. Report p99 only with at least 100
eligible observations and include the exact count. For errors, rejections, and timeouts report counts and
rates. Plot or tabulate replicate-level results so drift and heterogeneity remain visible.

## Effects

For each primary metric report baseline, candidate, absolute effect, relative effect, direction, and
confidence interval. Relative effects with a zero or unstable denominator are invalid; use absolute
effects. Keep latency reduction signs unambiguous by naming the estimand.

## Confidence intervals

Use paired bootstrap intervals with 10,000 resamples when requests are paired and the estimand supports
resampling. Preserve session or block structure when within-block correlation matters. For independent
runs, bootstrap or model replicate-level effects. Record method, resamples, confidence level, seed,
pairing key, and interval type.

Bootstrap percentile intervals are the V1 default for compact studies. More suitable methods are allowed
when preregistered and fully specified. A p-value alone is insufficient.

## Multiple metrics and decisions

Identify one primary metric per hypothesis. Secondary metrics explain mechanism; guardrails prevent
harm; quality metrics determine eligibility. If many candidates or endpoints drive a confirmatory claim,
record the multiplicity strategy. Exploratory effects remain labeled exploratory.

## Outliers and failures

No silent outlier removal. Any exclusion rule is predeclared, machine-checkable, reported with counts,
and accompanied by an all-data sensitivity result. Failed requests remain outcomes. System failures may
invalidate a run, but the failed attempt remains a draft record with logs and reason.

## Practical interpretation

Statistical detectability is separate from practical value. Findings state the effect relative to SLO,
cost, energy, resource, and quality thresholds. `no_effect` means a predeclared equivalence criterion was
met; otherwise use `inconclusive` when intervals include materially positive and negative effects.

## Transferability

Exact-setup confidence reflects evidence quality for the tested configuration. Transferability breadth
reflects replication across model, hardware, runtime, workload, traffic, topology, or scale axes. Never
inflate one because the other is high.
