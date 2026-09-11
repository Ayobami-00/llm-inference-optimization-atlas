# S004 - DeepSeek-V4.1 Engram placement and prefetch

S004 asks a deployment question with three directly paired conditions: keep the
two Engram tables in device HBM, place them in host RAM with synchronous access,
or place them in host RAM and arm the preview runtime's asynchronous layer-14
decode prefetch.

The originally preregistered primary endpoint was SLO-qualified offered-load
capacity for a frozen 8K/32K/128K production mixture. Mechanism evidence covers
server readiness, available KV-token capacity, HBM and host displacement,
context-by-concurrency TTFT/TPOT/throughput, scheduler state, and failure
boundaries. Reliable per-run PCIe byte counters were not available, so the
accepted evidence does not attribute latency to host-device transfer.
The original confirmatory design specified five paired blocks with independent
server initialization and identical traces. Compute cost constrained the
release-day publication to one complete paired block. Amendment 003 records
when that decision was made and requires every effect to remain descriptive;
the resulting study cannot estimate run-to-run variance or support a general
deployment recommendation.

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

[Amendment 003](experiments/E0013/AMENDMENT-003-cost-constrained-single-block-publication.md)
records the post-data reduction from five planned blocks to one published
block. The remaining four blocks were not run; they are neither failed nor
invalid evidence.

## One-block result

The accepted block consists of device run R3464, host-sync run R3465, and
host-prefetch run R3466. All three passed Q0: 48 fixed cases per configuration,
144 executions in total, produced exact greedy token-ID agreement with complete,
finite, well-formed responses and no treatment fallback. Machine health and the
independent AIPerf measurement cross-check also passed for every configuration.

Moving Engram to host memory reduced SGLang's reported model-weight residency
from 119.043 to 72.201 GB per GPU. With the memory fraction frozen at 0.80, the
reported KV-token pool increased from 11,841,280 to 42,697,728 tokens: an
additional 30,856,448 slots, or 260.6%. Mean system host memory increased from
107.12 GiB in device mode to 308.92 GiB for host-sync and 301.70 GiB for
host-prefetch. These are exact-setup observations from one block, not estimates
of a population effect.

Host-prefetch did not establish the preregistered performance recovery. Relative
to host-sync, its run-level mean TTFT changed by +2.25%, mean TPOT by +1.30%,
and output throughput by -1.27%. Across the nine unique-prefix cells at
concurrency 8 or greater, throughput improved in four and regressed in five;
the median effect was -0.29%, ranging from -6.56% to +2.45%. Relative to device
mode, host-prefetch's run-level mean TTFT was 15.57% higher, TPOT was 10.91%
higher, and output throughput was 14.36% lower.

No configuration passed the complete SLO at the lowest tested 0.2 request/s
rate because the 8K class missed its TTFT and TPOT limits. SLO-qualified
capacity is therefore left-censored below 0.2 request/s for all three modes.
The stored MET099 value of 0.0 is a sentinel for no qualifying tested rate, not
zero physical serving capacity, and its relative effect is intentionally null.

The formal decision is [DEC0004](decisions/DEC0004.yaml): `no_recommendation`.
Device placement is the observed performance reference when its 11.84M-token
KV pool is sufficient. Host placement is a memory-constrained option that needs
application-specific latency validation. The remaining independent blocks and
a lower-rate capacity bracket are required before making a general deployment
recommendation.

## Atlas evidence path

Readers can follow the complete graph from [the workload](workload.yaml) through
[the hypothesis](hypotheses/HYP013.yaml), [the experiment](experiments/E0013/experiment.yaml),
the three accepted runs and comparisons, [the findings](findings), and
[the decision](decisions/DEC0004.yaml). Comparison effects retain exact
content-family, context, concurrency, and prefix scopes for native tables,
filters, and context-by-concurrency heatmaps. Because there is only one paired
block, the comparison records are explicitly marked `descriptive_only` and do
not manufacture confidence intervals.

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
output belong in Git. Accepted evidence was privacy-scanned, checksummed, and
promoted through the Atlas contribution flow.
