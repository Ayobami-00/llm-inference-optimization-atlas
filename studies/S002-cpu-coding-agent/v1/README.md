# S002 — CPU coding agent

This study runs Qwen2.5-Coder-0.5B-Instruct Q4_K_M through a pinned llama.cpp HTTP
server on `HW001`. Six repository-owned coding tasks exercise prefix reuse,
thread budgets 1/4/8, one versus two server slots, and controlled 256/512/1024
token request shapes.

The full profile produced 30 accepted runs, six comparisons, six findings, and
decision `DEC0002`. The exact-setup recommendation uses warm prefix reuse, four
threads, one slot, and the representative 512-token request shape. Warm reuse
halved TTFT; one and eight threads both more than doubled TPOT relative to four.

Generated code is executed only in an ephemeral non-root Docker sandbox with no
network, a read-only root, tmpfs, dropped capabilities, CPU/memory/PID limits,
and hard timeouts.

```bash
uv run atlas execution prepare S002-cpu-coding-agent llama-cpp-cpu-server
uv run atlas execution run S002-cpu-coding-agent llama-cpp-cpu-server --profile quick
uv run atlas graph build S002-cpu-coding-agent
uv run atlas graph serve S002-cpu-coding-agent
```
