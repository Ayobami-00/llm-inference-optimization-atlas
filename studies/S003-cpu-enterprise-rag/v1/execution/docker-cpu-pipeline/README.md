# Native and Dockerized CPU RAG bundle

This bundle embeds a 24-document fictional enterprise corpus with the upstream all-MiniLM-L6-v2 ONNX
exports, retrieves by cosine similarity, and generates grounded answers with the pinned SmolLM2 revision.
The same worker runs natively and in a container built from an immutable multi-architecture Python base.
`atlas execution prepare` builds that image before the offline experiment lifecycle begins.

The response retains SmolLM2's synthesis verbatim in `model_synthesis` and appends an explicitly labelled
extractive evidence excerpt plus a deterministic citation from the top retrieved record. This makes the
compact study useful for retrieval, representation, and environment comparisons without pretending that
the 135M-parameter generator is a reliable standalone enterprise answerer. Client TTFT includes retrieval,
tokenization, and measured first-token emission; TPOT and ITL come from token-by-token timestamps.

The container receives only read-only repository and artifact-cache mounts, has no network, drops all
capabilities, enables no-new-privileges, and runs with bounded CPU, memory, PID, and temporary storage.
Model artifacts never enter the image or Git history. The image ID and every upstream artifact checksum are
retained in draft evidence.
