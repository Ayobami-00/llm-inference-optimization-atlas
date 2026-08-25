# Native llama.cpp CPU server bundle

This bundle compiles the exact b9637 llama.cpp source revision with Metal disabled, then serves the pinned
Qwen2.5-Coder-0.5B-Instruct Q4_K_M GGUF over loopback HTTP. Compilation output lives in the ignored shared
cache. Each runtime condition gets a fresh server process, so thread, slot, context, and prefix-cache changes
are explicit.

`atlas execution prepare` performs the platform-specific compilation and pulls the sandbox image by its
immutable digest. `atlas execution run` is then offline apart from the loopback model-server connection;
it fails instead of silently provisioning either dependency.

Generated Python is never executed on the host. The evaluator uses an ephemeral, non-root Docker container
with no network, a read-only root filesystem, a small tmpfs, no capabilities, no-new-privileges, and CPU,
memory, PID, and wall-time limits. The container image must be prepared before running; accepted evidence
records its immutable digest.
