from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from functools import lru_cache

CONTENT_FAMILIES = ("natural_language", "code", "high_entropy")
CONTEXT_CONCURRENCY = {
    1024: (1, 8, 32, 64),
    8192: (1, 8, 32, 64),
    32768: (1, 8, 32),
    131072: (1, 4, 8),
}
CAPACITY_CONTEXTS = (
    (8192, 0.50, "context-8k"),
    (32768, 0.35, "context-32k"),
    (131072, 0.15, "context-128k"),
)

NATURAL_SEED = (
    "Production incident timeline: the inference gateway received a burst of long-context "
    "requests after a dependency recovered. Operators compared queue growth, first-token "
    "latency, token cadence, cache pressure, and error handling before selecting a safe "
    "capacity envelope. The report preserves evidence, limitations, and remediation steps. "
)
CODE_SEED = '''def reconcile_request(request, scheduler, telemetry):
    """Return a deterministic record for an inference request."""
    started = telemetry.monotonic_ns()
    result = scheduler.generate(request)
    assert result.output_tokens >= 0
    return {"request_id": request.id, "elapsed_ns": telemetry.monotonic_ns() - started}

def test_reconcile_request_is_accounted_once():
    assert reconcile_request(fake_request(), fake_scheduler(), fake_clock())["request_id"]
'''


@dataclass(frozen=True)
class RequestSpec:
    request_id: str
    input_ids: tuple[int, ...]
    output_tokens: int
    request_class: str
    load_cell_id: str
    content_family: str
    target_context_tokens: int
    target_concurrency: int
    target_offered_rate: float | None = None
    scheduled_offset_seconds: float | None = None

    def public_record(self) -> dict[str, object]:
        record = asdict(self)
        record["input_ids_sha256"] = hashlib.sha256(
            json.dumps(self.input_ids, separators=(",", ":")).encode()
        ).hexdigest()
        del record["input_ids"]
        return record


def _repeat_to_length(values: Sequence[int], length: int) -> list[int]:
    if not values:
        raise ValueError("Tokenizer returned no ordinary tokens")
    quotient, remainder = divmod(length, len(values))
    return list(values) * quotient + list(values[:remainder])


def _unique_prefix(
    encode: Callable[[str], list[int]], seed: int, ordinal: int, namespace: str
) -> list[int]:
    prefix = encode(
        f" {seed:08d}-{ordinal:08d} {namespace} atlas unique request evidence boundary "
    )
    return _repeat_to_length(prefix, 32)


@lru_cache(maxsize=8)
def _ordinary_token_ids(vocab_size: int, forbidden: tuple[int, ...]) -> tuple[int, ...]:
    excluded = set(forbidden)
    return tuple(value for value in range(128, vocab_size) if value not in excluded)


def exact_content_tokens(
    *,
    family: str,
    target_tokens: int,
    seed: int,
    ordinal: int,
    encode: Callable[[str], list[int]],
    vocab_size: int,
    special_token_ids: Iterable[int],
    shared_prefix: Sequence[int] | None = None,
    prefix_namespace: str = "generated",
) -> tuple[int, ...]:
    """Create an exact-length token sequence without relying on post-hoc estimates."""

    if family not in CONTENT_FAMILIES:
        raise ValueError(f"Unknown content family: {family}")
    if target_tokens < 33:
        raise ValueError("S004 inputs reserve 32 tokens for a prefix")
    prefix = (
        list(shared_prefix)
        if shared_prefix is not None
        else _unique_prefix(encode, seed, ordinal, prefix_namespace)
    )
    prefix = _repeat_to_length(prefix, 32)
    payload_length = target_tokens - len(prefix)
    if family == "natural_language":
        payload = _repeat_to_length(encode(NATURAL_SEED), payload_length)
    elif family == "code":
        payload = _repeat_to_length(encode(CODE_SEED), payload_length)
    else:
        forbidden = tuple(sorted(int(value) for value in special_token_ids))
        ordinary = _ordinary_token_ids(vocab_size, forbidden)
        if not ordinary:
            raise ValueError("No ordinary token IDs are available for high-entropy content")
        rng = random.Random((seed << 32) ^ ordinal)
        start = rng.randrange(len(ordinary))
        step = rng.randrange(1, len(ordinary) + 1)
        while math.gcd(step, len(ordinary)) != 1:
            step = (step + 1) % len(ordinary) or 1
        payload = [
            ordinary[(start + index * step) % len(ordinary)] for index in range(payload_length)
        ]
    result = tuple(prefix + payload)
    if len(result) != target_tokens:
        raise AssertionError(f"Expected {target_tokens} tokens, generated {len(result)}")
    return result


def matrix_request(
    *,
    context_tokens: int,
    concurrency: int,
    family: str,
    seed: int,
    ordinal: int,
    encode: Callable[[str], list[int]],
    vocab_size: int,
    special_token_ids: Iterable[int],
    repeated_prefix: bool = False,
) -> RequestSpec:
    if concurrency not in CONTEXT_CONCURRENCY.get(context_tokens, ()) and not (
        repeated_prefix and context_tokens == 32768 and concurrency == 8
    ):
        raise ValueError(
            f"Unregistered matrix cell: context={context_tokens}, concurrency={concurrency}"
        )
    shared = None
    if repeated_prefix:
        shared_length = context_tokens // 2
        shared = _repeat_to_length(encode(" shared production conversation prefix "), shared_length)
        # The exact-content helper owns the 32-token prefix. Build the remaining
        # shared portion explicitly so every repeated-prefix request is identical
        # for precisely half of the target input.
        tail = exact_content_tokens(
            family=family,
            target_tokens=context_tokens - shared_length + 32,
            seed=seed,
            ordinal=ordinal,
            encode=encode,
            vocab_size=vocab_size,
            special_token_ids=special_token_ids,
        )[32:]
        tokens = tuple(shared + list(tail))
        cell = "prefix-context-32768-concurrency-8"
    else:
        tokens = exact_content_tokens(
            family=family,
            target_tokens=context_tokens,
            seed=seed,
            ordinal=ordinal,
            encode=encode,
            vocab_size=vocab_size,
            special_token_ids=special_token_ids,
            prefix_namespace=f"matrix-{context_tokens}-{concurrency}-{family}",
        )
        cell = f"context-{context_tokens}-concurrency-{concurrency}"
    return RequestSpec(
        request_id=(
            f"{'prefix' if repeated_prefix else 'matrix'}-"
            f"{seed}-{context_tokens}-{concurrency}-{family}-{ordinal}"
        ),
        input_ids=tokens,
        output_tokens=64,
        request_class=f"context-{context_tokens}",
        load_cell_id=cell,
        content_family=family,
        target_context_tokens=context_tokens,
        target_concurrency=concurrency,
    )


def poisson_offsets(rate: float, duration_seconds: float, seed: int) -> list[float]:
    if rate <= 0 or duration_seconds <= 0:
        raise ValueError("Rate and duration must be positive")
    rng = random.Random(seed)
    offsets: list[float] = []
    current = 0.0
    while True:
        current += rng.expovariate(rate)
        if current >= duration_seconds:
            break
        offsets.append(current)
    return offsets


def _capacity_contexts(count: int, rng: random.Random) -> list[tuple[int, str]]:
    """Stratify Poisson arrivals to the closest feasible frozen context mixture."""

    if count <= 0:
        return []
    minimum = 1 if count >= len(CAPACITY_CONTEXTS) else 0
    counts = [minimum] * len(CAPACITY_CONTEXTS)
    remaining = count - sum(counts)
    quotas = [remaining * weight for _, weight, _ in CAPACITY_CONTEXTS]
    for index, quota in enumerate(quotas):
        counts[index] += math.floor(quota)
    unallocated = count - sum(counts)
    remainder_order = sorted(
        range(len(CAPACITY_CONTEXTS)),
        key=lambda index: (-(quotas[index] - math.floor(quotas[index])), index),
    )
    for index in remainder_order[:unallocated]:
        counts[index] += 1
    assignments = [
        (tokens, request_class)
        for (tokens, _, request_class), allocation in zip(CAPACITY_CONTEXTS, counts, strict=True)
        for _ in range(allocation)
    ]
    rng.shuffle(assignments)
    return assignments


def capacity_trace(
    *,
    rate: float,
    duration_seconds: float,
    seed: int,
    encode: Callable[[str], list[int]],
    vocab_size: int,
    special_token_ids: Iterable[int],
) -> list[RequestSpec]:
    offsets = poisson_offsets(rate, duration_seconds, seed)
    rng = random.Random(seed ^ 0x5A004)
    trace = []
    context_ordinals: dict[int, int] = {}
    contexts = _capacity_contexts(len(offsets), rng)
    for ordinal, (offset, (context_tokens, request_class)) in enumerate(
        zip(offsets, contexts, strict=True)
    ):
        context_ordinal = context_ordinals.get(context_tokens, 0)
        family = CONTENT_FAMILIES[context_ordinal % len(CONTENT_FAMILIES)]
        context_ordinals[context_tokens] = context_ordinal + 1
        trace.append(
            RequestSpec(
                request_id=f"capacity-{seed}-{rate:.8f}-{ordinal}",
                input_ids=exact_content_tokens(
                    family=family,
                    target_tokens=context_tokens,
                    seed=seed,
                    ordinal=ordinal,
                    encode=encode,
                    vocab_size=vocab_size,
                    special_token_ids=special_token_ids,
                ),
                output_tokens=256,
                request_class=request_class,
                load_cell_id=f"capacity-rate-{rate:.8f}",
                content_family=family,
                target_context_tokens=context_tokens,
                target_concurrency=0,
                target_offered_rate=rate,
                scheduled_offset_seconds=offset,
            )
        )
    return trace


def trace_fingerprint(requests: Sequence[RequestSpec]) -> str:
    records = [request.public_record() for request in requests]
    return hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def reconcile_request_ids(
    expected: Sequence[RequestSpec], observed: Sequence[dict[str, object]]
) -> None:
    expected_ids = [request.request_id for request in expected]
    observed_ids = [str(row.get("request_id")) for row in observed]
    duplicates = sorted({value for value in observed_ids if observed_ids.count(value) > 1})
    missing = sorted(set(expected_ids) - set(observed_ids))
    unexpected = sorted(set(observed_ids) - set(expected_ids))
    if duplicates or missing or unexpected or len(expected_ids) != len(observed_ids):
        raise ValueError(
            "Request accounting mismatch: "
            f"expected={len(expected_ids)} observed={len(observed_ids)} "
            f"duplicates={duplicates[:5]} missing={missing[:5]} unexpected={unexpected[:5]}"
        )


def relative_boundary_width(low: float, high: float) -> float:
    if low <= 0 or high < low:
        return math.inf
    return (high - low) / low
