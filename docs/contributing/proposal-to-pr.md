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
uv run atlas proposal new study --output proposal.yaml
uv run atlas proposal validate proposal.yaml
uv run atlas proposal render proposal.yaml
uv run atlas proposal create-issue proposal.yaml
```

The final command is an external write and asks for confirmation. Automation
labels a valid proposal `proposal:valid`; only maintainers apply
`proposal:approved`.

## 2. Branch and scaffold

After approval, use the issue number in a standardized branch:

```text
feat/<issue>-<slug>
fix/<issue>-<slug>
chore/<issue>-<slug>
docs/<issue>-<slug>
```

Create a study with `atlas study new <proposal-path-or-P####>`, or add an
experiment with `atlas experiment new <study>`. Complete `contribution.yaml`
with the approved issue, proposal ID/type, scope, and contributor declarations.

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
`contribution.yaml` matches its type and scope. Reviewers may accept run evidence
while requesting narrower findings. Merge closes the proposal and rebuilds the
global and per-study Pages projections.
