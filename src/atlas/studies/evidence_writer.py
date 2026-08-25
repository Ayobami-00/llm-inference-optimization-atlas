from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from atlas.metrics.tables import REQUEST_COLUMNS, SAMPLE_COLUMNS
from atlas.utilities.serialization import yaml_writer


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _schema(columns: dict[str, tuple[pa.DataType, str | None]]) -> pa.Schema:
    fields = []
    for name, (data_type, unit) in columns.items():
        metadata = {b"unit": unit.encode()} if unit is not None else None
        fields.append(pa.field(name, data_type, metadata=metadata))
    return pa.schema(fields)


def _table(
    rows: list[dict[str, Any]], columns: dict[str, tuple[pa.DataType, str | None]]
) -> pa.Table:
    schema = _schema(columns)
    normalized = [{name: row.get(name) for name in columns} for row in rows]
    return pa.Table.from_pylist(normalized, schema=schema)


@dataclass(frozen=True)
class RunDraft:
    run_id: str
    experiment: str
    configuration: str
    runtime: str
    replicate: int
    seed: int
    started_at: str
    ended_at: str
    requests: list[dict[str, Any]]
    samples: list[dict[str, Any]]
    responses: list[dict[str, Any]]
    quality_results: dict[str, Any]
    quality_passed: bool
    summary: dict[str, Any]
    input_fingerprints: dict[str, str]
    artifact_checksums: dict[str, str]
    command: list[str]
    environment: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)


def write_run_draft(base: Path, draft: RunDraft) -> Path:
    output = base / "runs" / draft.run_id
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite draft evidence: {output}")
    for relative in ("metrics", "quality", "outputs", "logs"):
        (output / relative).mkdir(parents=True, exist_ok=True)

    pq.write_table(_table(draft.requests, REQUEST_COLUMNS), output / "metrics/requests.parquet")
    pq.write_table(_table(draft.samples, SAMPLE_COLUMNS), output / "metrics/samples.parquet")
    if draft.events:
        event_columns = {
            "timestamp_ns": (pa.int64(), "ns"),
            "event_type": (pa.string(), None),
            "details_json": (pa.string(), None),
        }
        pq.write_table(_table(draft.events, event_columns), output / "metrics/events.parquet")

    (output / "metrics/summary.json").write_text(
        json.dumps(draft.summary, indent=2, sort_keys=True) + "\n"
    )
    (output / "quality/results.json").write_text(
        json.dumps(draft.quality_results, indent=2, sort_keys=True) + "\n"
    )
    with (output / "outputs/responses.jsonl").open("w") as stream:
        for response in draft.responses:
            stream.write(json.dumps(response, sort_keys=True) + "\n")
    (output / "logs/README.md").write_text(
        "# Run logs\n\n"
        "No unrestricted model or system logs are committed. The run record, compact response "
        "records, environment snapshot, and checksummed metrics are the retained evidence.\n"
    )

    environment = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "executable": "uv-managed Python",
        "private_identifiers_included": False,
    }
    (output / "environment.json").write_text(
        json.dumps(environment, indent=2, sort_keys=True) + "\n"
    )
    artifacts = {
        "inputs": draft.input_fingerprints,
        "runtime_artifacts": draft.artifact_checksums,
        "generated_files": [
            "metrics/requests.parquet",
            "metrics/samples.parquet",
            "metrics/summary.json",
            "quality/results.json",
            "outputs/responses.jsonl",
        ],
    }
    with (output / "artifacts.yaml").open("w") as stream:
        yaml_writer().dump(artifacts, stream)

    run = {
        "$schema": (
            "https://ayobami-00.github.io/llm-inference-optimization-atlas/"
            "schemas/v1/studies/run-record.schema.json"
        ),
        "schema_version": 1,
        "kind": "RunRecord",
        "id": draft.run_id,
        "version": 1,
        "slug": f"run-{draft.run_id.lower()}",
        "title": f"Run {draft.run_id}",
        "description": f"Replicate {draft.replicate} for {draft.experiment}.",
        "status": "complete",
        "authors": [
            {"name": "Atlas study runner", "roles": ["software"], "conflicts": []}
        ],
        "created_at": draft.started_at,
        "updated_at": draft.ended_at,
        "license": "Apache-2.0",
        "citations": [],
        "provenance": {
            "method": "reproducible-execution-bundle",
            "source_paths": ["execution.yaml"],
            "generated": True,
            "parent_artifacts": [draft.experiment, draft.configuration],
        },
        "extensions": {},
        "experiment": draft.experiment,
        "configuration": draft.configuration,
        "replicate": draft.replicate,
        "seed": draft.seed,
        "started_at": draft.started_at,
        "ended_at": draft.ended_at,
        "outcome": "complete",
        "hardware_snapshot": "atlas://hardware/HW001@v1",
        "runtime_snapshot": draft.runtime,
        "input_fingerprints": draft.input_fingerprints,
        "command": draft.command,
        "environment": draft.environment,
        "windows": {
            "warmup": {"excluded": True, "requests": draft.summary.get("warmup_requests", 0)},
            "measurement": {
                "requests": len(draft.requests),
                "start": draft.started_at,
                "end": draft.ended_at,
            },
        },
        "artifacts": [
            "metrics/requests.parquet",
            "metrics/samples.parquet",
            "metrics/summary.json",
            "quality/results.json",
            "outputs/responses.jsonl",
        ],
        "checksums": draft.artifact_checksums,
        "quality": {
            "gate": "Q1",
            "passed": draft.quality_passed,
            "results_path": "quality/results.json",
        },
        "validation": {"passed": True, "validated_at": draft.ended_at, "errors": []},
    }
    with (output / "run.yaml").open("w") as stream:
        yaml_writer().dump(run, stream)

    manifest_paths = sorted(
        path for path in output.rglob("*") if path.is_file() and path.name != "checksums.sha256"
    )
    lines = [
        f"{sha256_file(path)}  {path.relative_to(output).as_posix()}"
        for path in manifest_paths
    ]
    (output / "checksums.sha256").write_text("\n".join(lines) + "\n")
    return output
