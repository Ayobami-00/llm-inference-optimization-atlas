# S003 — CPU enterprise RAG

This study runs a 24-document, 12-question repository-owned RAG fixture using
all-MiniLM-L6-v2 ONNX embeddings and SmolLM2 generation. It compares FP32 with
ARM64-compatible INT8 embeddings, retrieval `top_k` 1/3/5, precomputed with
per-request full-corpus embeddings, and native with fresh Docker execution.

The corrected full profile explicitly applies the declared four intra-op and one
inter-op thread budget to both ONNX Runtime and PyTorch. It produced 27 accepted
runs, five comparisons, five findings, and decision `DEC0003`; all runs passed Q1
and `SLO003`.

For this exact fixture, native FP32 `top_k` 3 with precomputed document vectors is
selected. INT8 and online-embedding latency effects were inconclusive. `top_k` 3
recovered all expected documents. Fresh per-run Docker launch added 2.10 seconds
mean E2E because startup and model loading are attributed to the first measured
request and amortized over only 12 requests; this is not a warmed-container claim.

```bash
uv run atlas execution prepare S003-cpu-enterprise-rag docker-cpu-pipeline
uv run atlas execution run S003-cpu-enterprise-rag docker-cpu-pipeline --profile quick
uv run atlas graph build S003-cpu-enterprise-rag
uv run atlas graph serve S003-cpu-enterprise-rag
```

Responses retain raw model synthesis and transparently append a deterministic
evidence excerpt and citation. The Q1 gate evaluates the complete recorded output.
