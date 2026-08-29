# Contributing

The Atlas accepts reproducible studies, experiments, replications, negative or
inconclusive evidence, finding challenges, methodology improvements, source
records, and tooling changes.

## Proposal before implementation

Evidence-bearing work starts with the matching schema-backed GitHub issue form:

1. Submit a new study, experiment, replication, finding challenge, or methodology
   proposal. Use the GitHub form directly, or avoid hand-editing YAML with:

   ```bash
   uv run atlas proposal new study --guided --output proposal.yaml
   uv run atlas proposal validate proposal.yaml
   uv run atlas proposal create-issue proposal.yaml
   ```

2. Resolve validation feedback and wait for `proposal:approved`.
3. Create `feat/<issue>-<slug>`, `fix/<issue>-<slug>`,
   `chore/<issue>-<slug>`, or `docs/<issue>-<slug>`.
4. Materialize and scaffold directly from the approved issue:

   ```bash
   uv run atlas contribution start https://github.com/Ayobami-00/llm-inference-optimization-atlas/issues/123
   uv run atlas contribution status S004
   ```

5. Review the generated `contribution.yaml` and keep its declared artifact paths aligned
   with the approved contribution.
6. Produce draft evidence under `.atlas/work/`, validate it, and promote only new
   immutable accepted run IDs.
7. Submit a pull request using the repository template.

The scaffold creates `contribution.yaml`. The approval gate checks issue identity,
proposal type, exact committed proposal semantics, declared changed paths, branch
name, closure syntax, and the live `proposal:approved` label. Editing an approved
issue removes that approval until the changed scope is reviewed again. Bootstrap
studies S001–S003 exercise this same flow.

## Evidence review is separate from interpretation review

A run can be valid while a finding is too broad. Reviewers therefore evaluate:

- evidence integrity: exact configuration, provenance, checksums, Arrow column
  contracts, quality gate, SLO status, and immutable inputs;
- comparison validity: compatibility, deliberately changed axes, seeds,
  replicates, statistics, and reported uncertainty;
- interpretation: claim wording, mechanism, conditions, boundaries, limitations,
  confidence, and transferability.

External papers can explain a mechanism. Only accepted Atlas runs and comparisons
can support a measured Atlas finding.

## Local checks

```bash
make setup
make check
```

For focused work:

```bash
uv run atlas schema check
uv run atlas ontology check
uv run atlas sources check --build
uv run atlas ids check
uv run atlas validate --all --strict
uv run atlas graph build --all
npm run test:e2e --prefix site
uv run atlas contribution status S003
```

Ordinary checks do not download models. See
[docs/guides/reproduce-a-study.md](docs/guides/reproduce-a-study.md) before
running a real-model bundle.

## Research expectations

- Pin model, runtime, dataset, tokenizer, container, and source revisions.
- Record hardware topology without serial numbers, UUIDs, usernames, hostnames,
  MAC addresses, credentials, or other private identifiers.
- Freeze the workload, quality contract, SLO, and analysis before inspecting
  candidate results.
- Use at least three independent full-profile replicates for an accepted finding.
- Pair identical traces and seeds; randomize candidate order where appropriate.
- Exclude warm-up, retain failed attempts as drafts, and never silently remove
  outliers.
- Apply Q0/Q1/Q2 according to optimization impact class.
- Preserve positive, negative, mixed, and inconclusive results.
- Scope findings to the exact systems tested and name transfer boundaries.
- Never commit model weights, caches, generated graph/site output, private data,
  secrets, or unlicensed upstream content.

## Sources and ontology changes

Reuse existing terms and source records when they already cover the concept. If
a contribution introduces an externally grounded concept, add the authoritative
`SRC####` record and the ontology or registry change in the same pull request.
Sources are marked superseded or retracted rather than deleted. Generated reverse
“Referenced by” indexes are compiler output and must not be edited manually.

## Commits and pull requests

Use concise imperative Conventional Commit-style subjects:

```text
feat(study-s004): measure CPU admission control
fix(validation): reject unresolved source references
docs(protocols): clarify warm-up boundaries
```

Do not add generated-author, AI, or co-author attribution trailers. Keep generated
build output unstaged. A PR must explain the approved scope, validation performed,
evidence status, claim boundaries, and any follow-up work.

The full flow is documented in
[docs/contributing/proposal-to-pr.md](docs/contributing/proposal-to-pr.md).
