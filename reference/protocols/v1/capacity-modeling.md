# V1 capacity-modeling protocol

Capacity is the maximum sustainable offered load that meets the selected quality and SLO contract,
not the highest transient token rate observed during an overloaded run.

## Terms

- **Offered load**: requests or tokens presented per unit time.
- **Achieved throughput**: completed work per unit time regardless of SLO.
- **Goodput**: completed, quality-eligible requests or tokens within all required SLO limits.
- **Concurrency**: simultaneous outstanding requests.
- **Saturation point**: region where additional offered load primarily increases queueing or errors.
- **Headroom**: distance between selected operating load and validated capacity.

## Procedure

1. Fix workload distribution, traffic mode, quality contract, SLO, and server state.
2. Warm the system using the declared warm-up protocol.
3. Sweep offered load from clearly underloaded through saturation.
4. Use independent replicates and randomized load-level order when drift permits.
5. Measure queue delay, TTFT, TPOT/ITL, E2E, outcomes, throughput, goodput, utilization, memory, and
   relevant cache/scheduler metrics.
6. Identify the highest load whose confidence bounds satisfy the SLO and quality contract.
7. Repeat around the boundary with finer load steps.

Do not estimate capacity from a single concurrency point. Closed-loop concurrency sweeps and open-loop
arrival-rate sweeps answer related but different questions and must be labeled.

## Overload behavior

Report admission rejections, timeouts, cancellations, queue growth, preemption, eviction, and recovery
after load falls. A system that preserves latency by rejecting work may have good latency but lower
request goodput; both must be visible.

## Capacity envelopes

For mixed workloads, report capacity by request class and the tested mixture. A compact envelope may
vary one dominant shape axis, such as input length, output length, or concurrent tenants. Extrapolation
outside measured points is a model, not a finding, and includes model form, fit diagnostics, uncertainty,
and validation points.

## Resource and cost normalization

Record physical/logical cores, accelerator count, memory, power policy, runtime workers, and replicas.
Report per-device and total capacity. Cloud price and energy values include date, region, currency,
billing assumptions, measurement source, and idle allocation policy.

## Decision use

Deployment decisions select an operating point with explicit headroom and revisit triggers. They may
return no recommendation when the candidate does not satisfy quality/SLO constraints or the measured
range does not establish a stable capacity boundary.
