# V1 contribution-review protocol

## Proposal-first flow

1. Open a schema-backed study, experiment, replication, finding-challenge, or methodology proposal.
2. Automation validates required fields and marks the proposal valid or needing revision.
3. Maintainers review scope, scientific value, feasibility, licensing, security, and overlap.
4. `proposal:approved` authorizes implementation; it does not guarantee evidence acceptance.
5. Create `feat/<issue>-<slug>`, `fix/<issue>-<slug>`, `chore/<issue>-<slug>`, or
   `docs/<issue>-<slug>`.
6. Submit a PR with `contribution.yaml` resolving the approved issue/proposal.
7. CI validates contracts, references, evidence integrity, graph determinism, and site behavior.
8. Review evidence integrity separately from interpretation.

## Proposal review

Reviewers verify a falsifiable question, boundaries, representative workload, intended quality/SLO
contracts, candidate space, expected resources, licensing, security risk, and completion criteria.
Experiments state baseline, changed/frozen factors, metrics, replicates, stopping rule, and failure policy.

## Evidence review

Evidence reviewers inspect immutable identities, commands, environment/hardware/runtime snapshots,
input fingerprints, windows, request accounting, Arrow schemas/units, checksums, quality eligibility,
replicates, and compatibility. Ordinary CI must perform these checks without downloading models.

## Interpretation review

Interpretation reviewers check estimands, uncertainty, effect direction, failed/missing handling,
mechanism diagnostics, scope, causal wording, limitations, confidence, transferability, negative evidence,
and decision rationale.

## Source changes

The contributor who introduces an externally grounded concept adds or updates the source and referencing
ontology/registry artifact in the same PR. Reuse of an existing concept requires no source edit. Source
records are reviewed for authority, relevance, stable identity, upstream revision, and accurate linkage.
Superseded or retracted records are marked, never deleted.

## Approval and conflicts

Approval records capture issue URL, proposal ID/version, label, approver, timestamp, approved scope, and
conditions. Contributors and reviewers declare financial, employment, authorship, or competitive
conflicts relevant to the work. High-impact claims should receive an unconflicted interpretation review.

## Commit and merge expectations

Commits are small, verified, imperative, and human-readable. Generated builds, model weights, caches,
container layers, and private machine identifiers are excluded. Merge closes the proposal issue and
rebuilds global and per-study graph routes. Pushes, merges, Pages activation, and repository protection
changes remain explicit maintainer actions.
