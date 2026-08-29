# V1 load-generation protocol

## Goal

Generate requests whose semantics, shapes, timing, concurrency, session behavior, and locality match
the declared workload closely enough to answer the experiment question.

## Modes

- **Open loop**: arrivals follow the declared process independently of completion. Use for queueing,
  overload, and provisioned-capacity questions.
- **Closed loop**: each client waits for completion plus optional think time. Use for interactive users
  and agents whose next action depends on the previous response.
- **Offline batch**: all work is available; optimize completion time or throughput without interactive
  latency assumptions.
- **Trace replay**: preserve observed timestamps or inter-arrival times, with documented scaling.

## Arrival processes

Specify deterministic, Poisson, gamma, lognormal, empirical-trace, burst, or custom generation. Record
parameters, units, seed, start alignment, rate scaling, and whether scheduling catches up after client
delay. A load generator that cannot sustain target arrivals records lag and does not pretend offered load
was achieved.

## Client behavior

Record connection reuse, protocol, serialization, streaming, client count, async/event-loop model,
timeouts, retries, cancellation, backoff, and clock source. Retries are distinct logical attempts and
must not inflate successful request counts invisibly.

## Sessions and agents

Session IDs, turn ordering, think time, tool delay, context mutation, and termination conditions are
deterministic from trace plus seed. Closed-loop agent tests can use recorded tool outputs to isolate model
serving or real sandboxed tools to measure end-to-end behavior; the mode must be explicit.

## Warm-up and measurement

Warm-up executes representative shapes and is excluded from primary summaries. Measurement begins only
after the declared state condition or fixed warm-up count/time. Cooldown and cleanup are excluded. All
request timestamps are retained so reviewers can reconstruct windows.

## Clock and timestamp semantics

Use monotonic clocks for durations. Wall time is metadata. Capture:

- `t0`: client send;
- `t1`: server receive;
- `t2`: execution entry;
- `t3`: first generated token;
- `t4`: first token received by client;
- `t5`: final token received.

Missing internal timestamps remain null and their derived metrics are unavailable; they are never
substituted with client timestamps without changing the metric name.

## Validation

Before execution, validate unique request IDs, class proportions, timestamp order, token/shape bounds,
seed reproducibility, trace fingerprint, target duration/count, and expected load. After execution,
reconcile offered, accepted, completed, failed, rejected, timed out, and cancelled requests.

Workload trace research is represented by `atlas://source/SRC0086@v1`.
