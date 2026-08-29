# Proposal-to-PR workflow

The contribution gate prevents experiments from being designed after results are
known and gives maintainers a reviewable scope before contributors spend compute.

## 1. Propose

Choose the matching issue form: new study, new experiment, replication, finding
challenge, or methodology/tooling change. The form maps to a V1 proposal schema.
Include research questions, workload and quality boundaries, changed axes,
expected evidence, resource needs, licensing, and safety constraints.

For local drafting:

```bash
uv run atlas proposal new study --guided --output proposal.yaml
uv run atlas proposal validate proposal.yaml
uv run atlas proposal render proposal.yaml
uv run atlas proposal create-issue proposal.yaml
```

The final command is an external write and asks for confirmation. Automation
labels a valid proposal `proposal:valid`, comments with field-specific corrections
when it is invalid, and only maintainers apply `proposal:approved`. Any subsequent
semantic edit removes approval and requires review again.

## 2. Branch and scaffold

After approval, use the issue number in a standardized branch:

```text
feat/<issue>-<slug>
fix/<issue>-<slug>
chore/<issue>-<slug>
docs/<issue>-<slug>
```

Start from the approved issue URL:

```bash
uv run atlas contribution start https://github.com/Ayobami-00/llm-inference-optimization-atlas/issues/123
uv run atlas contribution status S004
```

The command materializes the issue as canonical `P####` YAML and creates the
study or proposal-aware experiment scaffold. A study scaffold includes workload,
quality, SLO, input, and execution guidance. An experiment scaffold allocates its
experiment, hypothesis, baseline/candidate configuration, and runtime-configuration
IDs together. Use `atlas ids next <kind> [--count N]` for additional artifacts.
After editing runtime settings or another referenced record, run
`atlas study resolve <study>` to refresh every configuration's resolved hashes.

Within an already approved new-study contribution, add preregistered experiments
with `atlas experiment new <study>`. To add an experiment to a merged study later,
open an experiment proposal and use `atlas contribution start <approved-issue-url>`.

## 3. Implement and produce evidence

Resolve reusable model, runtime, hardware, dataset, and evaluator records. Add an
external source only when a new concept or registry fact needs it. Preregister
baseline, candidates, frozen/changed factors, quality gates, metrics, seeds,
replicates, order, stopping rules, and failure policy before running candidates.

Execution implementation can organize bundle-local source and configuration as
needed. Preserve the mandatory wrapper contract and document preparation,
lifecycle, generated-code safety, and expected resources.

Follow [the reproduction guide](../guides/reproduce-a-study.md). Commit accepted
compact evidence, comparisons, findings, and decisions; never commit caches,
weights, image layers, or generated graph/site output.

## 4. Open the pull request

The PR template separates evidence from interpretation. Link the approved issue
and list exact commands executed. CI validates schemas, ontology, sources,
identities, Arrow data, checksums, comparison compatibility, findings, graph
determinism, frontend behavior, accessibility, locks, and dependencies without
downloading real models.

The approval workflow verifies the issue still has `proposal:approved` and that
the committed `proposal.yaml` exactly matches the approved issue's questions,
scope, artifacts, resources, and risks. Reviewers may accept run evidence while
requesting narrower findings. Merge closes the proposal and rebuilds the global
and per-study Pages projections.

At any point, `atlas contribution status <study>` reports the first unfinished
stage. Add `--check` when CI or a script should fail until publication-ready.
