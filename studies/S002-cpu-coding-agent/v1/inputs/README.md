# Coding-agent task set

`tasks.jsonl` contains six repository-owned Python tasks with deterministic assertions. They are
intentionally compact so a sub-billion-parameter model can produce measurable successes and
failures on a laptop CPU. The execution bundle supplies a repeated agent prefix and incrementally
grows context without changing the task semantics.

Generated code is untrusted. Evaluation occurs only in the bundle's no-network, non-root,
resource-limited Docker sandbox. The tasks and assertions are licensed under Apache-2.0.
