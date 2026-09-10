# S004 - DeepSeek-V4.1 Engram placement and prefetch

S004 asks a deployment question with three directly paired conditions: keep the
two Engram tables in device HBM, place them in host RAM with synchronous access,
or place them in host RAM and arm the preview runtime's asynchronous layer-14
decode prefetch.

The confirmatory result is SLO-qualified offered-load capacity for a frozen
8K/32K/128K production mixture. Mechanism evidence covers server readiness,
available KV-token capacity, HBM and host displacement, context-by-concurrency
TTFT/TPOT/throughput, scheduler state, PCIe activity, and failure boundaries.
Five paired blocks use independent server initialization and identical traces.

Preregistration amendment E0013-AMENDMENT-001 prospectively refines the hardware
health rule after two CFG021 attempts encountered sparse NVIDIA `0x4`
`SW_POWER_CAP` samples on a node reporting the expected 1000 W configured limit
at preflight. New attempts retain and report that incidence rather than treating
it alone as invalid, but must record the expected power limit for every GPU in
every mandatory sample. Missing observations, configured power-limit drift,
thermal or hardware slowdown, hardware power brake, Xid, and new ECC events
remain invalidating. Both pre-amendment attempts remain invalid, preserved only
in `.atlas/work`, and cannot enter the study.
See [the amendment](experiments/E0013/AMENDMENT-001-software-power-capping.md)
for its scope and temporal boundary.

The Atlas-native controller is intentionally narrow rather than a replacement
for a general benchmark suite: it preserves exact integer token IDs, the
class-stratified Poisson schedule, dispatch-lag invalidation, exact output-token
equivalence, SGLang treatment resolution, and Atlas evidence fields. To guard
against client-side measurement error, block 1 also runs NVIDIA AIPerf 0.12.0
against the exact same 32K/concurrency-8 token payloads for all three modes.
That non-confirmatory audit compares mean TTFT, mean ITL, and output throughput;
a disagreement blocks headline use until it is investigated but is never mixed
into the paired confirmatory estimates.

This preregistration deliberately exposes a day-zero support boundary: the
installed runtime only constructs the prefetch stream when the resolved model
has no vision layers, and only executes it for single-row decode. S004 therefore
requires an explicit text-only deployment profile and a successful treatment
resolution pilot before any confirmatory run. Unsupported or fallback attempts
remain in `.atlas/work` and cannot be promoted.

No model weights, provider identifiers, unrestricted logs, or generated site
output belong in Git. Accepted evidence is promoted through the Atlas
contribution flow after the paid execution completes.
