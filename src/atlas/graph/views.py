from __future__ import annotations

from typing import Any

VIEW_TYPES = {
    "story": {
        "name": "Story",
        "description": "Workload-to-decision narrative with external sources hidden by default.",
        "types": {
            "workload_archetype",
            "study",
            "workload",
            "traffic",
            "experiment",
            "finding",
            "decision",
        },
        "layout": "dagre",
    },
    "bottleneck": {
        "name": "Bottleneck",
        "description": "Workload pressures, bottlenecks, diagnostics, and candidate interventions.",
        "types": {
            "workload_archetype",
            "workload",
            "characteristic",
            "bottleneck",
            "optimization",
            "finding",
        },
        "layout": "cose",
    },
    "optimization": {
        "name": "Optimization",
        "description": "Optimization mechanisms, target bottlenecks, evidence, and boundaries.",
        "types": {"optimization", "bottleneck", "experiment", "comparison", "finding"},
        "layout": "cose",
    },
    "evidence": {
        "name": "Evidence",
        "description": (
            "Hypotheses, experiments, accepted runs, comparisons, findings, and replications."
        ),
        "types": {
            "hypothesis",
            "experiment",
            "run",
            "comparison",
            "finding",
            "replication",
        },
        "layout": "dagre",
    },
    "deployment": {
        "name": "Deployment",
        "description": (
            "Configuration choices, supporting evidence, rejected alternatives, and decisions."
        ),
        "types": {
            "decision",
            "finding",
            "comparison",
            "configuration",
            "model",
            "hardware",
            "runtime",
        },
        "layout": "dagre",
    },
    "all": {
        "name": "All",
        "description": "Complete compiled graph, including sources and negative evidence.",
        "types": set(),
        "layout": "cose",
    },
}


def compile_views(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    output = {}
    for identifier, definition in VIEW_TYPES.items():
        node_ids = {
            node["id"]
            for node in nodes
            if not definition["types"] or node["type"] in definition["types"]
        }
        selected_edges = [
            edge for edge in edges if edge["source"] in node_ids and edge["target"] in node_ids
        ]
        output[identifier] = {
            "id": identifier,
            "name": definition["name"],
            "description": definition["description"],
            "node_ids": sorted(node_ids),
            "edge_ids": sorted(edge["id"] for edge in selected_edges),
            "default_layout": definition["layout"],
            "filters": {"include_statuses": [], "include_negative_evidence": True},
        }
    return output
