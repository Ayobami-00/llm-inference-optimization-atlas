from __future__ import annotations

from pathlib import Path

from atlas.sources import build_source_catalog, check_sources

ROOT = Path(__file__).parents[2]


def test_source_catalog_generation_is_deterministic() -> None:
    report = check_sources(ROOT)
    assert report.ok
    catalog, bibliography = build_source_catalog(ROOT)
    first = (catalog.read_bytes(), bibliography.read_bytes())
    build_source_catalog(ROOT)
    second = (catalog.read_bytes(), bibliography.read_bytes())
    assert first == second
    assert bibliography.read_text().count("@") >= 100
