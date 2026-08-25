# ADR 0002: Accepted evidence is immutable

- Status: accepted
- Date: 2026-08-25

## Context

Overwriting an accepted run would silently alter every downstream comparison,
finding, decision, and graph path while preserving the same identity. Research
corrections need an auditable history rather than in-place replacement.

## Decision

`atlas evidence promote` creates a new accepted run directory and refuses an
existing ID. Accepted runs and findings are never overwritten. A correction
creates a new object and explicitly declares `supersedes` or `invalidates`.
Failed, interrupted, quick-profile, and rejected attempts remain ignored draft
records unless deliberately contributed as a failure artifact.

## Consequences

Every claim remains traceable to the bytes reviewed at acceptance, and graph
history can represent correction rather than conceal it. Corrections require new
IDs and downstream artifacts must explicitly move to the replacement evidence,
which adds bookkeeping but preserves scientific integrity.
