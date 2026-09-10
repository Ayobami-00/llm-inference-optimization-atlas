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
For CFG022 and CFG023, `layout=shared, pinned` is required; SGLang's unpinned
ATS fallback is not accepted as the preregistered treatment.

Those pilots also populate the pinned SGLang and FlashInfer compiled-kernel and
autotune caches for every treatment. The cache is then retained unchanged, so
`MET098` represents a warm-compilation-cache production restart. Per-request
prefix/KV state is still cleared according to the workload protocol.

Every condition starts in a new SGLang process. Logs, invalid attempts, failure
state, treatment resolution, capacity points, and full telemetry stay ignored
under `.atlas/work`. Only successfully validated candidates are promoted, at
which time Atlas allocates their permanent run IDs.

If a full invocation is interrupted, rerun the S004 runner against the same
timestamped work directory. Candidate-complete block/configuration pairs and a
complete collector pilot are discovered and skipped; failed attempts are kept
in numbered retry directories. After all 15 primary candidates complete, the
runner performs one non-confirmatory 256K natural-language feasibility request
under CFG023.
