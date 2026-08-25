# V1 CPU benchmarking protocol

CPU execution is a primary Atlas target, including x86-64, ARM64, hybrid consumer CPUs, integrated
memory systems, and virtualized/cloud environments.

## Inventory

Capture architecture, vendor/model, microarchitecture, sockets, physical cores, logical threads,
performance/efficiency core groups, ISA features, cache hierarchy, NUMA topology, memory capacity and
channels, OS/kernel, runtime libraries, and power mode. Exclude serial numbers and user/device IDs.

On macOS, record Apple chip class, performance/efficiency core counts, unified-memory capacity, macOS
build, Accelerate/Metal availability, and observed thermal/power state. A process selected for CPU
execution must not silently offload layers or operators to GPU/ANE.

## Threading

Record runtime thread pools separately: compute/intra-op, inter-op, BLAS/OpenMP, tokenizer, HTTP/server,
and load-generator threads. Environment variables such as `OMP_NUM_THREADS`, affinity, and spin-wait
settings are captured from an allowlist. More configured threads than physical cores is an intervention,
not a harmless default.

For hybrid CPUs, record whether affinity is unpinned, performance-core-only, efficiency-core-only, or
explicitly partitioned. When the OS does not expose reliable affinity, state that limitation.

## Frequency, power, and thermals

Use AC power or record battery state. Declare governor/power mode and background workload controls. Run
a thermal-stability pilot; capture available frequency, temperature, thermal-pressure, and power metrics.
Randomize order and use A-B-A when long runs may heat-soak the device. Throttled intervals are retained
and interpreted, not silently removed.

## Memory and NUMA

Record model residency, RSS, page faults, swap/compression, memory pressure, and NUMA placement where
available. A cold-start study distinguishes filesystem cache, model mapping/loading, graph compilation,
and first inference. On NUMA systems, bind or deliberately vary CPU and memory placement and record it.

## Runtime builds

Capture Python/framework/runtime versions, commits, compiler, build flags, BLAS/oneDNN/Accelerate,
quantization format, vector backends, graph/compile mode, and binary hashes. Native and container results
are separate configurations even when they use the same high-level package.

## Measurement hygiene

Keep the load generator from becoming the bottleneck; for single-host tests, measure its CPU use and
reserve capacity when practical. Disable unrelated heavy processes when possible, but do not claim a
sterile machine. Use monotonic timing, fixed inputs, deterministic seeds, and representative warm-up.

## Reporting

Report wall latency, goodput, CPU utilization denominator, memory, and thread budget at minimum. Avoid
cross-machine conclusions from model name and core count alone. Apple, Intel, AMD, cloud VM, and
container results stay scoped to their exact topology until replication.

Runtime context includes `atlas://source/SRC0064@v1`, `atlas://source/SRC0065@v1`,
`atlas://source/SRC0066@v1`, `atlas://source/SRC0073@v1`, and
`atlas://source/SRC0100@v1`.
