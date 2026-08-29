# Add a study

A study contribution moves through one visible sequence:

```text
proposal → approval → frozen design → experiments → execution → accepted runs
         → comparisons → findings → decision → graph publication
```

## Example question

Suppose the proposed study asks whether reusable prompt state reduces server TTFT
for repeated questions over a long document on CPU without failing Q1. The proposal
must name the workload archetype, traffic regime, baseline, intervention, frozen
factors, quality boundary, resources, licensing, risks, and transfer exclusions
before candidate results are inspected.

Create the proposal in the GitHub form or with guided authoring:

```bash
uv run atlas proposal new study --guided --output proposal.yaml
uv run atlas proposal validate proposal.yaml
uv run atlas proposal create-issue proposal.yaml
```

After a maintainer applies `proposal:approved`, create the required branch and start
from the issue itself:

```bash
git switch -c feat/123-cpu-long-context-prompt-reuse
uv run atlas contribution start https://github.com/Ayobami-00/llm-inference-optimization-atlas/issues/123
uv run atlas contribution status S004
```

The generated workload, quality, SLO, hypothesis, and configuration records contain
`extensions.atlas.scaffold` markers. These markers identify fields that still need
scientific judgment; remove each marker only after those fields are frozen. The
status command then advances to execution, evidence, comparison, interpretation,
decision, and publication checks.

After the configuration and runtime settings are frozen, refresh their immutable
input hashes without calculating them manually:

```bash
uv run atlas study resolve S004
```

Run a quick profile to prove the path, then the preregistered full profile. Validate
every draft before promotion, retain failed attempts in `.atlas/work`, and never
replace an accepted run ID. A finding may be positive, negative, mixed, or
inconclusive, but its scope cannot exceed the accepted comparison evidence.

Before opening the PR:

```bash
uv run atlas contribution status S004 --check
uv run atlas validate --all --strict
uv run atlas graph build --all
make check
```

The PR body links and closes the approved issue. CI reconstructs the proposal from
that issue and compares its semantic fields with the committed `proposal.yaml`, so
an implementation cannot silently broaden the approved research plan.
