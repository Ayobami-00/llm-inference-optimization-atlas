# SGLang 4x B200 execution bundle

This bundle is the sole confirmatory execution path for E0013. Its full profile
requires the privacy-safe HW002 topology and the exact RT004 runtime source
fingerprint. The portable quick profile uses a local fake server only to test
request accounting, lifecycle cleanup, evidence serialization, and validation;
it cannot support a finding.

Run `atlas execution prepare S004 sglang-b200` on the B200 node before the full
profile. Preparation resumes the official pinned Hugging Face snapshot into
`/workspace/models/DeepSeek-V4.1-Flash-dba1be0`, downloads only the 57 paths in
`inputs/model-manifest.yaml`, and verifies every byte before success. This
custom preparation path is necessary because two weight shards exceed 100 GB
and require resumable transfers.

The provider image already contains the CUDA/SGLang scientific stack but lacks
Atlas's YAML reader. Install the lockfile-pinned `ruamel-yaml==0.19.1` into the
isolated `/workspace/atlas-deps` target and place that target plus the checkout's
`src` directory on `PYTHONPATH` when invoking Atlas. The execution scripts do
this automatically. Runtime fingerprinting deliberately removes `PYTHONPATH`
before inventorying the underlying SGLang image, so this tool-only dependency
does not alter the frozen scientific package manifest.

```bash
uv pip install --target /workspace/atlas-deps 'ruamel-yaml==0.19.1'
```

Install the independent standard-driver audit into its own virtual environment;
do not install it into the SGLang image environment. The full runner verifies
the exact AIPerf version before starting a model process.

```bash
uv venv --python 3.12 /workspace/aiperf-venv
uv pip install --python /workspace/aiperf-venv/bin/python 'aiperf==0.12.0'
```

During block 1, each configuration receives one non-confirmatory AIPerf audit
of 96 exact-token 32K requests at concurrency 8. The Atlas controller and
AIPerf each execute the identical trace after separate cache flushes. Payloads,
driver-level rows, and all AIPerf exports remain under `.atlas/work`; the run
summary retains only the version, payload fingerprint, shape checks, and
agreement result. AIPerf disagreement invalidates the attempt and prevents
headline publication until investigated, but its observations are not pooled
with the confirmatory Atlas measurements.

Before the collector pilot or any confirmatory request, the full runner starts
and stops each of CFG021, CFG022, and CFG023 once. All three requested Engram
modes must resolve from the pinned runtime logs. Any fallback or unsupported
mode is retained under `.atlas/work` and stops execution before measurement.
For CFG022 and CFG023, both Engram layers must report `layout=shared, pinned`
on every tensor-parallel rank; SGLang's unpinned ATS fallback is not accepted
as the preregistered treatment. CFG023 must also report its prefetch stream on
every tensor-parallel rank.

All three conditions explicitly set the runtime's normalized flat
`vision_n_layers` field to zero. Setting only `vision_config` to null is not a
text-only override in the pinned SGLang parser: it normalizes away without
changing the model's 32 flattened vision layers, which also makes Engram KV
prefetch ineligible. The resolved raw override is machine-checked through
`/server_info` before a pilot may pass.

Those pilots also populate the pinned SGLang and FlashInfer compiled-kernel and
autotune caches for every treatment. The cache is then retained unchanged, so
`MET098` represents a warm-compilation-cache production restart. Per-request
prefix/KV state is still cleared according to the workload protocol.

Every condition starts in a new SGLang process. Logs, invalid attempts, failure
state, treatment resolution, capacity points, and full telemetry stay ignored
under `.atlas/work`. Only successfully validated candidates are promoted, at
which time Atlas allocates their permanent run IDs.

Hardware-health evaluation follows prospective amendment
E0013-AMENDMENT-001. Preflight verifies the preregistered 1000 W configured
power limit, and the collector records a readable limit for every GPU alongside
every mandatory clock-event sample. A `0x4` `SW_POWER_CAP` sample is retained
and reported but is not sufficient to reject a new attempt while that limit is
unchanged. A missing or changed configured limit, `0x8` hardware slowdown,
`0x20` software thermal slowdown, `0x40` hardware thermal slowdown, `0x80`
hardware power brake, Xid, or a new ECC error rejects the attempt. The two
attempts completed before the amendment stay invalid and the runner must not
resume either as an accepted candidate.

The amended telemetry path has its own collector-on/off overhead pilot under
`collector-pilot-amendment-001`. The earlier pilot remains preserved, but it
cannot authorize the additional `power.limit` query used by new confirmatory
runs. The amended pilot records and checks the health-policy version, exact GPU
query fields, and runner fingerprint before it can be reused.

Collector shutdown allows the full bounded GPU-health, PCIe, and scheduler
sampling cycle to finish. If the collector is still active after that bound, it
records a terminal collector error and the attempt cannot become evidence.

The open-loop client prestarts its bounded worker pool before starting each
Poisson clock. Dispatch lag is measured at worker entry, independently of HTTP
payload construction. Each capacity point writes its excluded stabilization
trace and its measured trace, rows, and responses before applying the lag or
SLO gates, so an invalid point remains auditable under `.atlas/work`.

If a full invocation is interrupted, rerun the S004 runner against the same
timestamped work directory. Candidate-complete block/configuration pairs and a
complete, fingerprint-matched amended collector pilot are discovered and
skipped. A retained treatment
pilot is reused only after the current runner recomputes its treatment state
from the raw server log and verifies its retained preflight and `/server_info`;
failed attempts are kept in numbered retry directories. After all 15 primary
candidates complete, the runner performs one non-confirmatory 256K
natural-language feasibility request under CFG023.

Before promotion, finalize each mutable `R0000` candidate and then run the
ordinary evidence validator:

```bash
python -m atlas.studies.runners.s004_finalize \
  .atlas/work/.../candidates/runs/block-1-CFG021 \
  --server-log .atlas/work/.../attempts/block-1-CFG021-retry-2/server/server.log
atlas evidence validate .atlas/work/.../candidates/runs/block-1-CFG021
atlas evidence promote .atlas/work/.../candidates/runs/block-1-CFG021
```

Finalization derives, rather than hand-authors, the publication flags from the
retained capacity points and search boundary. `slo_passed` means at least one
tested offered rate satisfied every preregistered class SLO. `slo_eligible`
means the capacity result has a reportable resolved or censored boundary.
Consequently, a left-censored search is eligible evidence with
`slo_passed: false` and `MET099: 0`: zero means no qualifying rate in the
declared tested domain, not a claim of zero physical service capacity. The
finalizer records its policy and implementation fingerprints and reseals the
draft checksum manifest. It refuses an allocated run, so accepted evidence is
never mutated.

The finalizer also converts the retained server log into privacy-safe diagnostic
counts and a source-log fingerprint. PyTorch 2.13 reports a warning at
`CUDACachingAllocator.cpp:3933` for an initial failed `cudaMalloc`, including
cases where the caching allocator releases cached blocks, retries, and the
request completes. This behavior is documented in PyTorch's
[allocator issue 193195](https://github.com/pytorch/pytorch/issues/193195) and
[v2.13.0 retry path](https://github.com/pytorch/pytorch/blob/v2.13.0/c10/cuda/CUDACachingAllocator.cpp#L1770-L1792).
The study reports these as allocator memory-pressure retry warnings, separately
from a raised `torch.OutOfMemoryError`, request failure, or server failure. A
real OOM failure remains invalid under the frozen failure policy; a recovered
allocator retry is not relabeled as a failed request.
