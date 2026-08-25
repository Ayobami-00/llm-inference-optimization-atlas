# Contributing

The Atlas accepts reproducible evidence, replications, negative results,
methodology improvements, and tooling changes.

## Evidence contribution flow

1. Open the appropriate schema-backed proposal issue.
2. Wait for the `proposal:approved` label.
3. Create a branch named `feat/<issue>-<slug>`, `fix/<issue>-<slug>`,
   `chore/<issue>-<slug>`, or `docs/<issue>-<slug>`.
4. Scaffold the contribution with the `atlas` CLI.
5. Run local validation and include the approved issue in `contribution.yaml`.
6. Submit a pull request using the repository template.

Evidence acceptance and interpretation acceptance are separate. A valid run may
be accepted while an overly broad finding is narrowed or rejected.

## Commit messages

Use concise, imperative Conventional Commit-style subjects, for example:

```text
feat(study-s001): measure CPU batching under interactive chat
fix(validation): reject unresolved source references
docs(protocols): clarify warm-up boundaries
```

Do not include generated-author or AI attribution trailers.

## Research expectations

- Pin model, runtime, dataset, and tokenizer revisions.
- Record the complete hardware topology and runtime configuration.
- Use identical inputs and seeds for controlled comparisons.
- Separate warm-up from measurement.
- Run the quality gate required by the optimization impact class.
- Scope findings to the evidence actually produced.
- Retain negative and inconclusive results.
- Never commit secrets, private machine identifiers, gated data, or model weights.

Detailed protocols and templates live under `reference/`.
