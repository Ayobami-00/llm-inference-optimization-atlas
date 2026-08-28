from __future__ import annotations

import argparse
import json
import re
import time
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
import psutil
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _embed(session: ort.InferenceSession, tokenizer: Any, texts: list[str]) -> np.ndarray:
    encoded = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=256,
        return_tensors="np",
    )
    inputs = {}
    names = {item.name for item in session.get_inputs()}
    for name in names:
        if name in encoded:
            inputs[name] = encoded[name].astype(np.int64)
    token_embeddings = session.run(None, inputs)[0]
    mask = encoded["attention_mask"][:, :, None].astype(np.float32)
    pooled = (token_embeddings * mask).sum(axis=1) / np.clip(mask.sum(axis=1), 1e-9, None)
    normalized = pooled / np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-9, None)
    return np.asarray(normalized, dtype=np.float32)


def _generate(tokenizer: Any, model: Any, prompt: str) -> dict[str, Any]:
    started = time.perf_counter()
    encoded = tokenizer(prompt, truncation=True, max_length=448, return_tensors="pt")
    input_tokens = int(encoded["attention_mask"].sum())
    generated_tokens = []
    emitted_at = []
    with torch.inference_mode():
        output = model(**encoded, use_cache=True)
        next_token = torch.argmax(output.logits[:, -1, :], dim=-1, keepdim=True)
        cache = output.past_key_values
        for _ in range(64):
            generated_tokens.append(next_token)
            emitted_at.append(time.perf_counter())
            if int(next_token.item()) == tokenizer.eos_token_id:
                break
            output = model(input_ids=next_token, past_key_values=cache, use_cache=True)
            cache = output.past_key_values
            next_token = torch.argmax(output.logits[:, -1, :], dim=-1, keepdim=True)
    ended = emitted_at[-1]
    generated = torch.cat(generated_tokens, dim=1)[0]
    output_tokens = len(generated_tokens)
    text = tokenizer.decode(generated, skip_special_tokens=True)
    elapsed_ms = (ended - started) * 1000
    inter_token_ms = [(current - previous) * 1000 for previous, current in pairwise(emitted_at)]
    tpot_ms = (
        float(np.mean(inter_token_ms)) if inter_token_ms else elapsed_ms / max(output_tokens, 1)
    )
    return {
        "text": text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "generation_ms": elapsed_ms,
        "ttft_ms": (emitted_at[0] - started) * 1000,
        "tpot_ms": tpot_ms,
        "itl_p95_ms": float(np.percentile(inter_token_ms, 95)) if inter_token_ms else tpot_ms,
    }


def execute(args: argparse.Namespace) -> dict[str, Any]:
    process_started = time.perf_counter()
    torch.set_num_threads(args.intra_op_threads)
    torch.set_num_interop_threads(args.inter_op_threads)
    condition = json.loads(args.condition.read_text())
    documents = _jsonl(args.documents)
    questions = _jsonl(args.questions)[: args.request_limit]
    embedding_tokenizer = AutoTokenizer.from_pretrained(args.embedding_model, local_files_only=True)
    model_name = "model-int8.onnx" if condition["representation"] == "int8" else "model.onnx"
    options = ort.SessionOptions()
    options.intra_op_num_threads = args.intra_op_threads
    options.inter_op_num_threads = args.inter_op_threads
    embedding_session = ort.InferenceSession(
        str(args.embedding_model / model_name),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    generation_tokenizer = AutoTokenizer.from_pretrained(
        args.generation_model, local_files_only=True
    )
    generation_model = AutoModelForCausalLM.from_pretrained(
        args.generation_model, local_files_only=True
    )
    generation_model.eval()
    document_text = [f"{item['title']}. {item['text']}" for item in documents]
    document_embeddings = None
    if condition["embeddings"] == "precomputed":
        document_embeddings = _embed(embedding_session, embedding_tokenizer, document_text)
    startup_ms = (time.perf_counter() - process_started) * 1000
    process = psutil.Process()
    measured_at = time.perf_counter()
    cpu_started = process.cpu_times()
    rows = []
    responses = []
    for question in questions:
        request_started = time.perf_counter()
        if document_embeddings is None:
            current_documents = _embed(embedding_session, embedding_tokenizer, document_text)
        else:
            current_documents = document_embeddings
        query = _embed(embedding_session, embedding_tokenizer, [question["question"]])[0]
        similarities = current_documents @ query
        top_k = int(condition["top_k"])
        indexes = np.argsort(-similarities)[:top_k]
        retrieved = [documents[int(index)] for index in indexes]
        context = "\n".join(f"[{item['id']}] {item['title']}: {item['text']}" for item in retrieved)
        prompt = (
            "Answer the question using only the supplied records. State the answer directly and "
            "preserve exact numbers and time periods.\n\n"
            f"Records:\n{context}\n\nQuestion: {question['question']}\nAnswer:"
        )
        before_generation_ms = (time.perf_counter() - request_started) * 1000
        generated = _generate(generation_tokenizer, generation_model, prompt)
        source_ids = [item["id"] for item in retrieved]
        primary_source = retrieved[0]
        synthesis = re.sub(r"\bDOC[0-9]{3}\b", "record", generated["text"]).strip()
        text = (
            f"{synthesis}\nEvidence excerpt: {primary_source['text']}\n"
            f"Sources: {primary_source['id']}"
        ).strip()
        e2e_ms = (time.perf_counter() - request_started) * 1000
        responses.append(
            {
                "request_id": question["id"],
                "text": text,
                "retrieved_docs": source_ids,
                "relevant_docs": question["relevant_docs"],
                "answer_keywords": question["answer_keywords"],
                "model_synthesis": generated["text"],
            }
        )
        rows.append(
            {
                "request_id": question["id"],
                "request_class": "grounded-question",
                "input_tokens": generated["input_tokens"],
                "output_tokens": generated["output_tokens"],
                "ttft_client_ms": before_generation_ms + generated["ttft_ms"],
                "tpot_ms": generated["tpot_ms"],
                "itl_mean_ms": generated["tpot_ms"],
                "itl_p95_ms": generated["itl_p95_ms"],
                "e2e_ms": e2e_ms,
                "queue_ms": 0.0,
            }
        )
    elapsed_seconds = time.perf_counter() - measured_at
    cpu_ended = process.cpu_times()
    cpu_seconds = (cpu_ended.user + cpu_ended.system) - (cpu_started.user + cpu_started.system)
    return {
        "startup_ms": startup_ms,
        "elapsed_seconds": elapsed_seconds,
        "rss_bytes": int(process.memory_info().rss),
        "cpu_ratio": cpu_seconds / max(elapsed_seconds, 1e-9),
        "rows": rows,
        "responses": responses,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--condition", type=Path, required=True)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--embedding-model", type=Path, required=True)
    parser.add_argument("--generation-model", type=Path, required=True)
    parser.add_argument("--request-limit", type=int, required=True)
    parser.add_argument("--intra-op-threads", type=int, required=True)
    parser.add_argument("--inter-op-threads", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args), sort_keys=True))


if __name__ == "__main__":
    main()
