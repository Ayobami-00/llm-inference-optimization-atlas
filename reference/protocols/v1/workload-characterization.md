# V1 workload characterization protocol

An inference result is interpretable only relative to the work presented to the system. A workload
specification records semantics, request shapes, traffic, sessions, locality, retrieval, and server
state independently so each can be held constant or deliberately varied.

## Semantic population

Record the source dataset or repository-owned corpus, immutable version or digest, license,
acquisition date, filters, transformations, sampling frame, and excluded population. Describe the
product behavior the sample stands for and what it does not represent. Synthetic data must state the
generator, parameters, seed, and validation against the intended shape or semantic distribution.

Never label a token-shape trace as representative of semantic quality. A shape replay can establish
systems behavior but cannot evaluate answer quality unless paired with suitable semantic inputs.

## Request shapes

At minimum characterize:

- input, requested output, observed output, and total-context token counts;
- p50, p90, p95, minimum, maximum, and sample count;
- modality sizes such as image resolution, frame count, audio duration, or retrieved chunks;
- request classes and their proportions;
- truncation, padding, chat-template, tokenizer, and stopping behavior.

Use the exact model tokenizer for token distributions. When comparing models with different
tokenizers, retain source-level sizes and report per-model tokenization.

## Sessions and locality

Record turns per session, think/tool delays, cancellation behavior, context growth, prefix overlap,
document reuse, temporal reuse, and tenant boundaries. Prefix or KV reuse experiments must identify
which bytes/tokens are shared and whether reuse is legal across sessions or tenants.

## Traffic

Select or define a traffic regime and record:

- open-loop or closed-loop generation;
- arrival process and target rate;
- concurrency and queue limits;
- burst window and burst ratio;
- user, tool, or feedback delays;
- overload and admission behavior;
- trace duration and seed.

For open-loop tests, offered load remains independent of service latency. For closed-loop tests,
clients issue new work after completion or a specified think time. Results from the two modes are not
directly interchangeable.

## Server state

Every run selects one initial state:

- **STATE-COLD**: process stopped; model and caches absent from process memory.
- **STATE-MODEL-LOADED**: model initialized; request/KV caches empty.
- **STATE-WARM**: warm-up workload completed; relevant kernels and allocators exercised.
- **STATE-STEADY**: defined load has reached a measured stable interval.

Filesystem page cache, container cache, compiled graphs, prefix cache, embedding indexes, and remote
cache state must be stated separately when they matter.

## Replay fidelity

Semantic replay preserves content and order. Shape replay preserves timing and declared dimensions but
may substitute content. Hybrid replay preserves a semantic subset and models the remainder. Always
record trace transformation and fingerprint. Identical controlled comparisons use identical traces and
seeds unless the changed factor is the trace itself.

## Minimum characterization checklist

An accepted experiment has a workload fingerprint, traffic mode, request classes, token/shape
distributions, warm-up and measurement boundaries, seed, initial state, quality contract, and SLO.
Limitations explicitly cover missing production behaviors such as authentication, network distance,
multi-tenancy, user cancellation, tool execution, or long-tail content.

Dataset and trace examples are grounded by `atlas://source/SRC0085@v1`,
`atlas://source/SRC0086@v1`, and `atlas://source/SRC0087@v1`.
