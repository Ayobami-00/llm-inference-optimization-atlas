from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from atlas.metrics.tables import REQUEST_COLUMNS, SAMPLE_COLUMNS, validate_result_tables


def _empty_table(columns: dict[str, tuple[pa.DataType, str | None]]) -> pa.Table:
    fields = []
    arrays = []
    for name, (data_type, unit) in columns.items():
        metadata = {b"unit": unit.encode()} if unit else None
        fields.append(pa.field(name, data_type, metadata=metadata))
        arrays.append(pa.array([], type=data_type))
    return pa.Table.from_arrays(arrays, schema=pa.schema(fields))


def test_arrow_contract_checks_types_and_units(tmp_path: Path) -> None:
    pq.write_table(_empty_table(REQUEST_COLUMNS), tmp_path / "requests.parquet")
    pq.write_table(_empty_table(SAMPLE_COLUMNS), tmp_path / "samples.parquet")
    assert validate_result_tables(tmp_path) == []

    bad = _empty_table(REQUEST_COLUMNS).set_column(
        0,
        pa.field("request_id", pa.int64()),
        pa.array([], type=pa.int64()),
    )
    pq.write_table(bad, tmp_path / "requests.parquet")
    assert any("request_id must be string" in error for error in validate_result_tables(tmp_path))
