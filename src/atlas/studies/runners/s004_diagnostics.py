from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from atlas.studies.evidence_writer import sha256_file

_ALLOCATOR_RETRY_PATTERN = re.compile(
    r"CUDACachingAllocator\.cpp:(?P<source_line>[0-9]+)\].*?"
    r"memory allocation failed with OOM on device (?P<device>[0-9]+) "
    r"while trying to allocate (?P<requested_bytes>[0-9]+) bytes "
    r"\(free: (?P<free_bytes>[0-9]+), total: (?P<total_bytes>[0-9]+)\)",
    re.IGNORECASE,
)
_FATAL_OOM_PATTERNS = (
    re.compile(r"\btorch\.OutOfMemoryError\b"),
    re.compile(r"\bCUDA out of memory\b", re.IGNORECASE),
)


def server_log_diagnostics(server_log: Path) -> dict[str, Any]:
    """Return privacy-safe, deterministic diagnostics from an S004 server log.

    PyTorch 2.13 emits ``CUDACachingAllocator.cpp:3933`` warnings for an
    initial ``cudaMalloc`` failure even when its caching allocator recovers by
    releasing cached blocks and retrying. Those warnings are counted as memory
    pressure; they are deliberately kept distinct from a raised OOM exception.
    """

    if server_log.is_symlink() or not server_log.is_file():
        raise ValueError("Server log must be a regular, non-symlinked file")
    text = server_log.read_text(errors="replace")
    batch_sizes = [
        int(match.group(1))
        for match in re.finditer(r"#running-req:\s*([0-9]+)", text, re.IGNORECASE)
    ]
    warnings = [
        {name: int(value) for name, value in match.groupdict().items()}
        for match in _ALLOCATOR_RETRY_PATTERN.finditer(text)
    ]
    by_device = Counter(warning["device"] for warning in warnings)
    requested_bytes = Counter(warning["requested_bytes"] for warning in warnings)
    fatal_oom_mentions = sum(len(pattern.findall(text)) for pattern in _FATAL_OOM_PATTERNS)
    if fatal_oom_mentions:
        allocator_classification = "fatal-oom-signal-present"
    elif warnings:
        allocator_classification = "allocator-retry-warnings-without-fatal-exception"
    else:
        allocator_classification = "no-allocator-memory-pressure-warning"
    return {
        "maximum_reported_running_batch": max(batch_sizes, default=0),
        "reported_running_batch_observations": len(batch_sizes),
        "preemption_log_mentions": len(re.findall(r"\bpreempt(?:ion|ed|ing)?\b", text, re.I)),
        "fallback_log_mentions": len(re.findall(r"\bfallback\b", text, re.I)),
        "allocator_memory_pressure": {
            "classification": allocator_classification,
            "retry_warning_count": len(warnings),
            "fatal_oom_exception_mentions": fatal_oom_mentions,
            "retry_warnings_by_device": {
                str(device): count for device, count in sorted(by_device.items())
            },
            "requested_allocation_bytes": [
                {"bytes": byte_count, "count": count}
                for byte_count, count in sorted(requested_bytes.items())
            ],
            "source_locations": sorted(
                {f"CUDACachingAllocator.cpp:{warning['source_line']}" for warning in warnings}
            ),
            "source_log_sha256": sha256_file(server_log),
        },
    }
