# V1 findings and claims protocol

## Finding anatomy

An accepted finding states:

- a scoped, testable statement;
- observed baseline and intervention;
- absolute and relative effects with uncertainty;
- workload, traffic, model, runtime, hardware, topology, and configuration scope;
- conditions where the result holds and known stopping conditions;
- interactions and limitations;
- run and comparison evidence;
- exact-setup confidence and transferability breadth;
- claim status: supported, contradicted, mixed, no-effect, inconclusive, superseded, or invalidated.

## Scope rule

Finding scope is the intersection of compatible evidence scopes. It cannot expand from one Apple M3 CPU
run to “CPUs,” from one quantized revision to a model family, from low concurrency to production load,
or from a compact quality suite to semantic equivalence. Broader language requires replication across the
named axes.

## Causal language

A controlled experiment can support that the deliberately changed factor caused an effect under the
tested conditions when frozen-factor compatibility and mechanism guardrails hold. Observational metrics
can associate a symptom with a bottleneck but cannot alone validate causality. The graph compiler rejects
causal relations whose evidence level is only theoretical, hypothetical, or observational.

## Mechanism

A mechanism explains why an effect may occur and points to diagnostic metrics and optional sources. A
mechanism source can strengthen plausibility but cannot substitute for measured effects. If diagnostics
do not support the expected mechanism, report that mismatch even when the primary metric improves.

## Negative and inconclusive evidence

Negative results are retained when the candidate degrades eligible performance or quality. `no_effect`
requires a predeclared smallest effect of interest/equivalence region. `inconclusive` is appropriate when
evidence cannot distinguish materially beneficial and harmful effects. Failed implementations remain
draft attempts, distinct from a valid negative comparison.

## Claim challenges and corrections

A finding challenge identifies disputed evidence, scope, method, or interpretation and proposes a
resolution path. Accepted findings are not edited to erase history. New artifacts `supersede` or
`invalidate` prior findings and graph edges preserve both records.

## Decisions

Decisions normally cite Atlas findings rather than external publications. They state selected
configuration, Pareto rationale, quality/SLO/resource/cost/energy envelope, rejected alternatives,
caveats, and revisit triggers. `no_recommendation` is a valid and useful outcome.

## Writing pattern

Prefer: “On HW001 with RT001, configuration CFG002 reduced median client TTFT by X relative to CFG001
for W001/T001 while passing QC001; the confidence interval was Y and transferability is narrow.” Avoid:
“Optimization X makes inference faster.”
