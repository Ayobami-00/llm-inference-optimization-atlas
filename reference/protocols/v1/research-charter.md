# V1 research charter

## Purpose

The Atlas records reproducible, scoped evidence about LLM inference systems. Its unit of truth is
not a paper claim, benchmark headline, or vendor specification. It is a comparison between
validated runs whose changed factors, quality eligibility, environment, and uncertainty are
explicit.

The canonical chain is:

```text
workload -> hypothesis -> experiment -> run -> comparison -> finding -> decision
```

External sources explain concepts and mechanisms. Only Atlas runs and comparisons support Atlas
findings.

## Research principles

1. Define workload, quality, and SLO contracts before observing candidate results.
2. Compare configurations only when all frozen factors are compatible.
3. Report latency distributions and SLO goodput, not only averages or raw throughput.
4. Keep exact-setup confidence separate from transferability.
5. Retain negative, mixed, and inconclusive outcomes.
6. Never silently remove outliers, failed requests, or warm/cold-state distinctions.
7. Treat CPU and consumer hardware as first-class environments.
8. Record immutable software, model, data, and hardware identities where practical.
9. Prefer a narrow defensible claim to a broad unsupported claim.
10. Make corrections through superseding or invalidating artifacts rather than rewriting accepted
    evidence.

## Evidence ladder

Graph assertions use these levels:

- `structural`: an identity or containment fact from canonical artifacts.
- `theoretical`: a mechanism or expectation grounded in sources, without Atlas measurement.
- `hypothetical`: a falsifiable prediction registered before measurement.
- `observational`: measured association without a controlled intervention.
- `experimentally_supported`: a controlled, quality-eligible comparison supports the claim.
- `replicated`: compatible independent evidence supports transfer beyond one exact setup.

No compiler or reviewer may infer a stronger level from the wording of a title or description.

## Baselines

- **B0** is the simplest working, correctness-eligible configuration available to the study.
- **B1** is the strongest representative configuration already in normal use or established by
  prior accepted evidence.

An experiment may compare against either or both. The selected baseline must be justified before
results are interpreted. A weak B0 comparison does not establish superiority to a tuned B1.

## Quality-impact classes

- `exact`: intended to preserve mathematical behavior, subject to implementation correctness.
- `numerically_non_exact`: may change floating-point accumulation or scheduling but is expected to
  preserve task behavior.
- `lossy`: intentionally discards precision, state, context, or computation.
- `model_transforming`: changes weights, architecture, routing, or learned behavior.

Q0 is always required. Q1 is normally required for numerical or scheduling changes. Q2 is
required for lossy or model-transforming interventions unless the study records a stricter rule.

## Research boundaries

The Atlas may establish that an optimization worked for a specific workload, model revision,
runtime build, hardware topology, traffic regime, and configuration. It does not establish an
optimization as universally best. Security, privacy, licensing, operational complexity, and
maintainability are legitimate decision constraints even when they are not performance metrics.

## Ethical and legal constraints

Experiments must not contain secrets, personal data without an approved lawful basis, proprietary
inputs that cannot be redistributed, or model/data use that conflicts with upstream terms. Generated
code and untrusted model output must be isolated with least privilege. Contributors declare relevant
conflicts and disclose sponsorship.

## Version and correction policy

Accepted artifacts are immutable. Corrections add an artifact with `supersedes` or `invalidates`,
preserving the prior object and the reason. Schema-compatible clarifications stay in V1. Breaking
contract changes require V2 after the V1 release boundary.

## External grounding

The charter adopts workload-aware serving and distributional latency principles represented by
`atlas://source/SRC0001@v1`, `atlas://source/SRC0002@v1`, and
`atlas://source/SRC0003@v1`. Those sources motivate methods; they do not count as Atlas findings.
