# V1 measurement protocol

## Measurement layers

Collect the least expensive tier that can answer the question and diagnose the expected mechanism:

- M0: mandatory request outcomes, tokens, latency, throughput, goodput, memory, utilization.
- M1: scheduler, batching, preemption, KV/cache, eviction, and offload.
- M2: CPU/GPU activity, bandwidth, interconnect, clocks, temperature, and power.
- M3: kernels, launch gaps, collectives, synchronization, and overlap.
- M4: accelerator-seconds and monetary cost.
- M5: energy and efficiency.

The 96 initial V1 metric definitions live in `reference/ontology/v1/metrics/`. The set may grow
compatibly within V1 as studies introduce a measurement that is both externally meaningful and
not already represented; existing IDs and semantics remain stable.

## Request table

`requests.parquet` has one row per logical attempt and includes request/session/class identity,
timestamps, outcome, input/output token counts, queue time, client/server TTFT when available, TPOT,
ITL summary, E2E, and quality eligibility. Units are stored in Arrow field metadata and validated by
the CLI.

## Samples and events

`samples.parquet` is long-form: timestamp, metric ID, value, unit, scope, device, and labels. Sampling
frequency and collector overhead are recorded. `events.parquet` stores discrete scheduler, cache,
allocation, lifecycle, error, and marker events. Missing instrumentation produces absent/null data, not
zeroes.

## Latency definitions

- client TTFT = `t4 - t0`;
- server TTFT = `t3 - t1`;
- queue delay = `t2 - t1`;
- E2E = `t5 - t0`;
- TPOT = generation interval divided by emitted-token intervals, with exact formula recorded;
- ITL is derived from token arrival timestamps and summarized per request.

Do not mix client and server TTFT in one distribution. State whether the first emitted item is an actual
generated token or protocol metadata.

## Throughput and goodput

Report completed requests/s and input/output/total tokens/s over the measurement window. Goodput counts
only requests satisfying outcome, quality, and all selected SLO constraints. Token throughput does not
replace request goodput for variable-length workloads.

## Resource measurement

State collector, version, permission level, sampling interval, device scope, aggregation, and expected
error. CPU utilization reports denominator (one core or whole host). Memory separates RSS, model bytes,
allocator-reserved, cache, swap, and accelerator memory where observable. Power reports source and
whether it is chip, package, device, or wall power.

## Perturbation and synchronization

Run a collector-on/off pilot when instrumentation may alter performance. Use one monotonic clock domain
where possible; otherwise record synchronization method and uncertainty. High-overhead profilers belong
in diagnostic runs and should not silently supply headline latency.

## Summaries

`summary.json` is derived from raw tables. It records count, mean, p50, p90, p95, conditional p99,
outcomes, throughput, goodput, resources, quality status, window, and generation metadata. Raw compact
evidence is canonical; the summary can be regenerated and checked.

Parquet format grounding is `atlas://source/SRC0076@v1`; runtime telemetry context includes
`atlas://source/SRC0083@v1` and `atlas://source/SRC0084@v1`.
