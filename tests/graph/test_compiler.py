from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from atlas.graph import GraphCompiler

ROOT = Path(__file__).parents[2]


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    assert isinstance(value, dict)
    return value


def _tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for file_path in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(file_path.relative_to(path).as_posix().encode())
        digest.update(file_path.read_bytes())
    return digest.hexdigest()


def test_graph_build_is_deterministic_and_resolved() -> None:
    compiler = GraphCompiler(ROOT)
    result = compiler.build()
    first_digest = _tree_digest(result.root)
    second = compiler.build()
    assert _tree_digest(second.root) == first_digest

    graph = _load(result.root / "graph.json")
    node_ids = {node["id"] for node in graph["nodes"]}
    assert len(node_ids) == len(graph["nodes"])
    assert all(edge["source"] in node_ids and edge["target"] in node_ids for edge in graph["edges"])


def test_views_are_subsets_and_story_hides_sources() -> None:
    output = GraphCompiler(ROOT).build().root
    graph = _load(output / "graph.json")
    node_ids = {node["id"] for node in graph["nodes"]}
    edge_ids = {edge["id"] for edge in graph["edges"]}
    story = _load(output / "views" / "story.json")
    assert set(story["node_ids"]) <= node_ids
    assert set(story["edge_ids"]) <= edge_ids
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert all(nodes[identifier]["type"] != "source" for identifier in story["node_ids"])


def test_source_reverse_references_are_generated() -> None:
    output = GraphCompiler(ROOT).build().root
    indexes = _load(output / "indexes.json")
    source = "atlas://source/SRC0002@v1"
    assert source in indexes["referenced_by"]
    assert any(
        reference.startswith("atlas://optimization/")
        for reference in indexes["referenced_by"][source]
    )


def test_claim_edges_always_carry_atlas_evidence() -> None:
    output = GraphCompiler(ROOT).build().root
    graph = _load(output / "graph.json")
    causal = {
        "IMPROVES",
        "DEGRADES",
        "NO_SIGNIFICANT_EFFECT",
        "VALIDATED_AS_BOTTLENECK",
    }
    for edge in graph["edges"]:
        if edge["relation"] in causal:
            assert edge["assertion_level"] in {"experimentally_supported", "replicated"}
            assert edge["evidence"]
