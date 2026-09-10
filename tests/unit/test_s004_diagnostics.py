from __future__ import annotations

from pathlib import Path

import pytest

from atlas.studies.runners.s004_diagnostics import server_log_diagnostics

_RETRY = (
    "[rank{device}]:[W910 23:40:43.144601916 CUDACachingAllocator.cpp:3933] "
    "memory allocation failed with OOM on device {device} while trying to allocate "
    "7516192768 bytes (free: 1547173888, total: 191495471104)."
)


def test_server_log_diagnostics_separates_allocator_retries_from_fatal_oom(
    tmp_path: Path,
) -> None:
    server_log = tmp_path / "server.log"
    server_log.write_text(
        "\n".join(
            [
                "Decode batch, #running-req: 8, #queue-req: 0",
                *(_RETRY.format(device=device) for device in range(4)),
                '127.0.0.1 - "POST /generate HTTP/1.1" 200 OK',
            ]
        )
    )

    diagnostics = server_log_diagnostics(server_log)

    assert diagnostics["maximum_reported_running_batch"] == 8
    memory_pressure = diagnostics["allocator_memory_pressure"]
    assert memory_pressure["classification"] == ("allocator-retry-warnings-without-fatal-exception")
    assert memory_pressure["retry_warning_count"] == 4
    assert memory_pressure["fatal_oom_exception_mentions"] == 0
    assert memory_pressure["retry_warnings_by_device"] == {
        "0": 1,
        "1": 1,
        "2": 1,
        "3": 1,
    }
    assert memory_pressure["requested_allocation_bytes"] == [{"bytes": 7516192768, "count": 4}]
    assert memory_pressure["source_locations"] == ["CUDACachingAllocator.cpp:3933"]
    assert len(memory_pressure["source_log_sha256"]) == 64


def test_server_log_diagnostics_identifies_fatal_oom_signal(tmp_path: Path) -> None:
    server_log = tmp_path / "server.log"
    server_log.write_text(
        _RETRY.format(device=0) + "\nraise torch.OutOfMemoryError: CUDA out of memory\n"
    )

    diagnostics = server_log_diagnostics(server_log)

    assert diagnostics["allocator_memory_pressure"]["classification"] == (
        "fatal-oom-signal-present"
    )
    assert diagnostics["allocator_memory_pressure"]["fatal_oom_exception_mentions"] == 2


def test_server_log_diagnostics_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "actual.log"
    target.write_text("ordinary log")
    server_log = tmp_path / "server.log"
    server_log.symlink_to(target)

    with pytest.raises(ValueError, match="regular, non-symlinked"):
        server_log_diagnostics(server_log)
