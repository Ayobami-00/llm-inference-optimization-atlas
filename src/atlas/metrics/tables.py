from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

REQUEST_COLUMNS: dict[str, tuple[pa.DataType, str | None]] = {
    "request_id": (pa.string(), None),
    "request_class": (pa.string(), None),
    "outcome": (pa.string(), None),
    "t0_ns": (pa.int64(), "ns"),
    "t5_ns": (pa.int64(), "ns"),
    "input_tokens": (pa.int64(), "token"),
    "output_tokens": (pa.int64(), "token"),
    "ttft_client_ms": (pa.float64(), "ms"),
    "tpot_ms": (pa.float64(), "ms/token"),
    "itl_mean_ms": (pa.float64(), "ms"),
    "itl_p95_ms": (pa.float64(), "ms"),
    "e2e_ms": (pa.float64(), "ms"),
    "queue_ms": (pa.float64(), "ms"),
    "quality_passed": (pa.bool_(), None),
}

SAMPLE_COLUMNS: dict[str, tuple[pa.DataType, str | None]] = {
    "timestamp_ns": (pa.int64(), "ns"),
    "metric_id": (pa.string(), None),
    "value": (pa.float64(), None),
    "unit": (pa.string(), None),
    "scope": (pa.string(), None),
}

EVENT_COLUMNS: dict[str, tuple[pa.DataType, str | None]] = {
    "timestamp_ns": (pa.int64(), "ns"),
    "event_type": (pa.string(), None),
    "details_json": (pa.string(), None),
}


def _validate_table(
    path: Path, expected: dict[str, tuple[pa.DataType, str | None]]
) -> list[str]:
    if not path.is_file():
        return [f"Missing table: {path}"]
    try:
        schema = pq.read_schema(path)
    except Exception as error:
        return [f"Cannot read {path}: {error}"]
    errors = []
    for name, (arrow_type, unit) in expected.items():
        field_index = schema.get_field_index(name)
        if field_index < 0:
            errors.append(f"{path}: missing required column {name}")
            continue
        field = schema.field(field_index)
        if field.type != arrow_type:
            errors.append(f"{path}: {name} must be {arrow_type}, found {field.type}")
        if unit is not None:
            actual = (field.metadata or {}).get(b"unit")
            if actual != unit.encode():
                rendered = actual.decode(errors="replace") if actual else "missing"
                errors.append(f"{path}: {name} unit must be {unit}, found {rendered}")
    return errors


def validate_result_tables(metrics_root: Path) -> list[str]:
    errors = []
    errors.extend(_validate_table(metrics_root / "requests.parquet", REQUEST_COLUMNS))
    errors.extend(_validate_table(metrics_root / "samples.parquet", SAMPLE_COLUMNS))
    events = metrics_root / "events.parquet"
    if events.exists():
        errors.extend(_validate_table(events, EVENT_COLUMNS))
    return errors
