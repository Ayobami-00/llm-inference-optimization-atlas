# Documentation

This directory explains how the versioned reference contracts, canonical study
records, local execution system, and generated evidence explorer fit together.
Normative research rules remain under `reference/protocols/v1`; these documents
are implementation and contributor guidance.

## Architecture

- [Repository and data flow](architecture/repository-and-data-flow.md)
- [Evidence graph compilation](architecture/evidence-graph.md)
- [Security and trust boundaries](architecture/security-and-trust-boundaries.md)

## Concepts

- [Artifact identity and versioning](concepts/artifact-model.md)
- [Evidence, claims, confidence, and transferability](concepts/evidence-and-claims.md)

## Guides

- [Reproduce a real-model study](guides/reproduce-a-study.md)
- [Explore global and per-study graphs](guides/explore-the-graph.md)

## Contributing

- [Add a study](contributing/add-a-study.md)
- [Proposal-to-PR workflow](contributing/proposal-to-pr.md)
- [Add or evolve an external source](contributing/add-a-source.md)

## Architecture decisions

- [ADR 0001: Git is the canonical database](decisions/0001-git-as-database.md)
- [ADR 0002: Accepted evidence is immutable](decisions/0002-immutable-accepted-evidence.md)
