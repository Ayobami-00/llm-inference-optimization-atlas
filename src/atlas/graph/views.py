from __future__ import annotations

from typing import Any

VIEW_TYPES = {
    "story": {
        "name": "Story",
        "description": "Follow the evaluated workload from study design to deployment decision.",
        "types": {
            "study",
            "workload",
            "experiment",
            "comparison",
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
            "Inspect hypotheses, grouped replicates, comparisons, findings, and replications."
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
            "See which findings justify a decision and which configurations it selects or rejects."
        ),
        "types": {
            "decision",
            "finding",
            "configuration",
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


PRESENTATION = {
    "story": {
        "stages": [
            {"label": "Workload", "types": ["workload"]},
            {"label": "Study", "types": ["study"]},
            {"label": "Experiments", "types": ["experiment"]},
            {"label": "Comparisons", "types": ["comparison"]},
            {"label": "Findings", "types": ["finding"]},
            {"label": "Decision", "types": ["decision"]},
        ],
        "intro": (
            "Read the columns from workload to decision; arrows preserve the recorded relation."
        ),
        "relations": ["PRODUCES", "SUPPORTS", "JUSTIFIES"],
    },
    "evidence": {
        "stages": [
            {"label": "Hypotheses", "types": ["hypothesis"]},
            {"label": "Experiments", "types": ["experiment"]},
            {"label": "Replicate groups", "types": ["run"]},
            {"label": "Comparisons", "types": ["comparison"]},
            {"label": "Findings", "types": ["finding", "replication"]},
        ],
        "intro": (
            "Replicate runs are grouped by experiment and configuration; "
            "select a group to expand it."
        ),
        "relations": ["TESTS", "HAS_RUN", "COMPARES", "SUPPORTS"],
        "compact_runs": True,
    },
    "deployment": {
        "stages": [
            {"label": "Findings", "types": ["finding"]},
            {"label": "Decision", "types": ["decision"]},
            {"label": "Configurations", "types": ["configuration"]},
        ],
        "intro": (
            "Read supporting findings into the decision, then inspect the selected "
            "and rejected configurations."
        ),
        "relations": ["JUSTIFIES", "USES_CONFIGURATION", "REJECTS"],
    },
}


GLOBAL_STORY_TYPES = {"workload_archetype", "workload", "study", "decision"}
GLOBAL_STORY_PRESENTATION = {
    "stages": [
        {"label": "Archetypes", "types": ["workload_archetype"]},
        {"label": "Workloads", "types": ["workload"]},
        {"label": "Studies", "types": ["study"]},
        {"label": "Decisions", "types": ["decision"]},
    ],
    "intro": "Start with a workload family, choose a study, and open its scoped decision.",
    "relations": ["INSTANCE_OF", "USES_CONFIGURATION", "PRODUCES"],
}


def compile_views(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    scope: dict[str, str],
) -> dict[str, dict[str, Any]]:
    output = {}
    for identifier, definition in VIEW_TYPES.items():
        selected_types = definition["types"]
        presentation = PRESENTATION.get(identifier)
        if identifier == "story" and scope["type"] == "global":
            selected_types = GLOBAL_STORY_TYPES
            presentation = GLOBAL_STORY_PRESENTATION
        node_ids = {
            node["id"]
            for node in nodes
            if not selected_types or node["type"] in selected_types
        }
        node_types = {node["id"]: node["type"] for node in nodes}
        selected_edges = [
            edge
            for edge in edges
            if edge["source"] in node_ids
            and edge["target"] in node_ids
            and not (
                identifier == "story"
                and scope["type"] == "study"
                and node_types[edge["source"]] == "study"
                and node_types[edge["target"]] == "decision"
            )
        ]
        output[identifier] = {
            "id": identifier,
            "name": definition["name"],
            "description": definition["description"],
            "node_ids": sorted(node_ids),
            "edge_ids": sorted(edge["id"] for edge in selected_edges),
            "default_layout": definition["layout"],
            "filters": {
                "include_statuses": [],
                "include_negative_evidence": True,
                **({"presentation": presentation} if presentation else {}),
            },
        }
    return output
