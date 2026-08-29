from __future__ import annotations

from io import StringIO

from atlas.utilities.serialization import yaml_writer


def test_yaml_writer_does_not_emit_trailing_space_when_scalars_are_long() -> None:
    stream = StringIO()
    yaml_writer().dump(
        {
            "$schema": "https://example.com/" + "long-path/" * 30 + "schema.json",
            "description": "a deliberately long scalar " * 30,
        },
        stream,
    )

    assert all(line == line.rstrip() for line in stream.getvalue().splitlines())
