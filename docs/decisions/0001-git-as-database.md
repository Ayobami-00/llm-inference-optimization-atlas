# ADR 0001: Git is the canonical database

- Status: accepted
- Date: 2026-08-25

## Context

The Atlas needs reviewable schema evolution, immutable evidence history, source
attribution, reproducible graph generation, and a contribution model that works
without operating a service.

## Decision

Versioned files in Git are canonical. JSON Schema defines contracts, YAML authors
objects, Parquet stores compact request/time-series measurements, JSON stores
summaries and generated projections, and Markdown explains protocols. The graph,
indexes, source catalog, bibliography, and site are deterministic build products.

No backend database or graph database is required for V1.

## Consequences

Pull requests expose every semantic and evidence change to normal review, and a
repository revision identifies a complete Atlas state. Contributors can validate
and explore locally. The design trades query-time flexibility and large-scale raw
telemetry retention for portability, transparency, and reproducibility; evidence
must therefore remain compact enough for Git.
