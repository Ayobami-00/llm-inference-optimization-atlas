# Security and trust boundaries

The Atlas treats model artifacts, generated text, contributed scripts, containers,
and external metadata as untrusted inputs until validated within their boundary.

## Network and artifact preparation

Validation, graph compilation, tests, and ordinary pull-request CI never download
models. `atlas execution prepare` is the explicit networked phase: it prints
artifact sizes and license metadata, requires confirmation unless `--yes` is
given, downloads into `.atlas/cache`, and verifies declared SHA-256 digests.
Accepted runs record artifact digests, not model weights.

## Execution

Execution bundles declare their resources and lifecycle. `run.sh` is mandatory;
`start.sh` and `destroy.sh` are mandatory when services or resources need setup
and cleanup. Cleanup runs after failure or interruption and must be idempotent.

S002 executes generated code only in an ephemeral non-root container with no
network, a read-only root filesystem, tmpfs scratch space, dropped capabilities,
`no-new-privileges`, CPU/memory/PID limits, and hard timeouts. The sandbox reduces
risk but does not make arbitrary contributed code trusted; reviewers must inspect
execution changes.

S003 uses a pinned immutable-base image and no network during measurement. Native
and container workers receive the same explicit thread contract. Its container
result includes launch and model-load overhead by design.

## Data and privacy

Repository fixtures are owned, synthetic, or redistribution-compatible. Hardware
records omit serial numbers, device UUIDs, MAC addresses, usernames, hostnames,
credentials, and private topology identifiers. Environment variables record a
redaction status, and secrets must never enter logs, outputs, checksums, or Git.

## GitHub and publishing

Issue proposals are public external writes and require explicit contributor
action or approved automation. Pull requests are approval-gated. Pages deployment
uses generated read-only artifacts; it cannot mutate canonical evidence. Enabling
Pages, pushing branches, merging, and changing branch protection remain separate
maintainer actions.
