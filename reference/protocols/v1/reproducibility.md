# V1 reproducibility protocol

## Reproducibility target

A reviewer should be able to understand the experiment without execution, validate committed evidence
without downloading models, and reproduce the run after explicitly preparing upstream artifacts.

## Execution-bundle interface

Each bundle contains:

```text
execution/<bundle>/
├── execution.yaml
├── README.md
├── run.sh
├── start.sh       # when a service/resource must be started
├── destroy.sh     # paired with start.sh
├── src/           # any implementation structure/language
└── config/
```

`run.sh` is mandatory. `start.sh` and `destroy.sh` are mandatory when lifecycle management is needed.
The internal layout is intentionally unconstrained. Wrappers use Bash 3.2-compatible syntax and resolve
paths relative to themselves, not the caller's working directory.

## Preparation

`atlas execution prepare` resolves declared artifacts, shows identity, license, and size, then downloads
only after consent into the shared `.atlas/cache`. It verifies checksums and records resolved paths.
Validation never downloads artifacts. Model weights, package caches, container layers, and generated
builds are never committed.

## Environment capture

Record repository commit/dirty state, command, working directory in repository-relative form, allowed
environment values and redaction state, package lock, binary/container digests, model/data fingerprints,
hardware/runtime snapshots, seeds, locale, timezone, and start/end timestamps. Secrets and private host
identifiers are excluded.

## Draft and accepted evidence

Execution writes to `.atlas/work/<attempt>` and never directly into accepted `runs/R####`. Interruptions
or failures trigger idempotent cleanup and preserve a failed draft record. Promotion validates schemas,
table columns/units, checksums, quality, references, and immutability before copying compact evidence to
the canonical run path. Existing accepted run IDs cannot be overwritten.

## Containers and generated code

Container images are pinned by digest when accepted. Multi-architecture support is explicit. Generated
code executes without network as non-root, with read-only root, tmpfs writable space, dropped
capabilities, CPU/memory/PID limits, and hard wall timeout. Model output never becomes shell syntax.

## Checksums

`checksums.sha256` covers every accepted evidence file except the checksum file itself, using stable
repository-relative names and sorted order. The run record stores input and output digests. Summaries
include generation code revision.

## Reproduction report

A replication records what was held constant, changed transfer axes, whether effects agree, confidence
impact, and newly observed boundaries. Bitwise identity is not required unless claimed; deviations are
measured and explained.

## Supported environments

V1 targets macOS ARM64 and Linux CPU. Windows is supported through WSL2 or Docker. Studies state tighter
requirements where runtime/model support differs.
