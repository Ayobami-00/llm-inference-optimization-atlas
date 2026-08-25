from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas.graph.model import EdgeSpec, Entity
from atlas.graph.views import compile_views
from atlas.schemas import SchemaCatalog
from atlas.utilities.repository import repository_relative
from atlas.utilities.serialization import canonical_json, dump_json
from atlas.validation import Validator
from atlas.validation.references import canonical_reference


class GraphError(RuntimeError):
    """Canonical artifacts cannot be compiled into a valid evidence graph."""


@dataclass(frozen=True)
class GraphBuild:
    root: Path
    nodes: int
    edges: int
    studies: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "path": str(self.root),
            "nodes": self.nodes,
            "edges": self.edges,
            "studies": list(self.studies),
        }


NODE_KIND = {
    "Source": "source",
    "WorkloadArchetype": "workload_archetype",
    "WorkloadSpec": "workload",
    "TrafficProfile": "traffic",
    "QualityContract": "quality_contract",
    "SLOProfile": "slo",
    "ModelRevision": "model",
    "HardwareTopology": "hardware",
    "RuntimeBuild": "runtime",
    "RuntimeConfiguration": "runtime",
    "Configuration": "configuration",
    "Bottleneck": "bottleneck",
    "Optimization": "optimization",
    "Hypothesis": "hypothesis",
    "Study": "study",
    "Experiment": "experiment",
    "RunRecord": "run",
    "Comparison": "comparison",
    "Finding": "finding",
    "DeploymentDecision": "decision",
    "Replication": "replication",
}

ONTOLOGY_NODE_KIND = (
    (re.compile(r"^W\d{3}$"), "workload_archetype"),
    (re.compile(r"^WC\d{3}$"), "characteristic"),
    (re.compile(r"^T\d{3}$"), "traffic"),
    (re.compile(r"^B\d{3}$"), "bottleneck"),
    (re.compile(r"^OPT\d{3}$"), "optimization"),
)

CAUSAL_RELATIONS = {
    "IMPROVES",
    "DEGRADES",
    "NO_SIGNIFICANT_EFFECT",
    "VALIDATED_AS_BOTTLENECK",
}


class GraphCompiler:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.catalog = SchemaCatalog(root / "reference" / "schemas" / "v1")

    def build(self, study: str | None = None) -> GraphBuild:
        validation = Validator(self.root).validate_path(self.root, strict=True)
        if not validation.ok:
            message = "; ".join(
                f"{issue.path}{issue.location}: {issue.message}" for issue in validation.errors
            )
            raise GraphError(f"Canonical validation failed: {message}")
        entities = self._entities(validation.artifacts)
        edges = self._edges(entities)
        nodes = sorted((entity.node for entity in entities.values()), key=lambda item: item["id"])
        edges = sorted(edges, key=lambda item: item["id"])
        self._validate_graph(nodes, edges)

        output = self.root / "build" / "atlas"
        if output.exists():
            expected = (self.root / "build" / "atlas").resolve()
            if output.resolve() != expected:
                raise GraphError(f"Refusing to replace unexpected output path: {output.resolve()}")
            shutil.rmtree(output)
        output.mkdir(parents=True)
        self._write_projection(output, nodes, edges, entities, {"type": "global"})

        study_entities = sorted(
            (entity for entity in entities.values() if entity.node["type"] == "study"),
            key=lambda entity: entity.reference,
        )
        studies = [entity.reference for entity in study_entities]
        selected = studies
        if study is not None:
            selected = [
                entity.reference
                for entity in study_entities
                if study
                in {
                    entity.reference,
                    str(entity.artifact.get("id", "")),
                    str(entity.artifact.get("slug", "")),
                    self._study_directory(entity),
                }
            ]
            if len(selected) != 1:
                raise GraphError(f"Expected one study matching {study!r}; found {len(selected)}")
        for study_reference in selected:
            study_nodes, study_edges = self._study_projection(study_reference, nodes, edges)
            study_entity = entities[study_reference]
            directory = self._study_directory(study_entity)
            destination = output / "studies" / directory / f"v{study_entity.artifact['version']}"
            self._write_projection(
                destination,
                study_nodes,
                study_edges,
                entities,
                {"type": "study", "study": study_reference},
            )
        return GraphBuild(output, len(nodes), len(edges), tuple(selected))

    def _entities(self, artifacts: list[Any]) -> dict[str, Entity]:
        entities: dict[str, Entity] = {}
        for loaded in artifacts:
            data = loaded.data
            if data.get("kind") == "OntologyCatalog":
                for entry in data.get("entries", []):
                    if not isinstance(entry, dict):
                        continue
                    node_type = self._ontology_type(str(entry.get("id", "")))
                    if not node_type:
                        continue
                    artifact = dict(entry)
                    artifact["ontology_catalog"] = data["id"]
                    entity = self._entity(
                        artifact,
                        loaded.path,
                        node_type,
                        int(data["version"]),
                    )
                    entities[entity.reference] = entity
                continue
            kind = str(data.get("kind", ""))
            node_type = NODE_KIND.get(kind)
            if not node_type:
                continue
            entity = self._entity(data, loaded.path, node_type, int(data.get("version", 1)))
            if entity.reference in entities:
                raise GraphError(f"Duplicate graph entity: {entity.reference}")
            entities[entity.reference] = entity
        return entities

    def _ontology_type(self, identifier: str) -> str | None:
        for pattern, node_type in ONTOLOGY_NODE_KIND:
            if pattern.fullmatch(identifier):
                return node_type
        return None

    def _entity(self, artifact: dict[str, Any], path: Path, node_type: str, version: int) -> Entity:
        identifier = str(artifact["id"])
        reference = canonical_reference(identifier, version, str(artifact.get("kind", "")))
        if reference is None:
            reference = self._ontology_reference(identifier, version, node_type)
        if reference is None:
            raise GraphError(f"Cannot derive graph identity for {identifier}")
        node = {
            "id": reference,
            "type": node_type,
            "label": str(artifact.get("title", artifact.get("name", identifier))),
            "status": str(artifact.get("status", "active")),
            "source_path": repository_relative(path, self.root),
            "artifact_ref": reference,
            "summary": str(artifact.get("description", artifact.get("definition", ""))),
            "tags": self._tags(artifact),
            "detail_path": f"entities/{identifier}@v{version}.json",
        }
        study = self._study_reference(artifact, path)
        if study:
            node["study"] = study
        return Entity(reference, node, artifact, path)

    def _ontology_reference(self, identifier: str, version: int, node_type: str) -> str | None:
        kind = {
            "workload_archetype": "workload",
            "characteristic": "workload-characteristic",
            "traffic": "traffic",
            "bottleneck": "bottleneck",
            "optimization": "optimization",
        }.get(node_type)
        return f"atlas://{kind}/{identifier}@v{version}" if kind else None

    def _tags(self, artifact: dict[str, Any]) -> list[str]:
        tags: list[str] = []
        for key in ("topics", "aliases", "modalities"):
            values = artifact.get(key, [])
            if isinstance(values, list):
                tags.extend(str(value) for value in values)
        for key in (
            "category",
            "level",
            "layer",
            "resource",
            "stage",
            "type",
            "result",
            "claim_status",
            "outcome",
        ):
            if artifact.get(key):
                tags.append(str(artifact[key]))
        return sorted(set(tags))

    def _study_reference(self, artifact: dict[str, Any], path: Path) -> str | None:
        if artifact.get("kind") == "Study":
            return canonical_reference(str(artifact["id"]), int(artifact["version"]), "Study")
        value = artifact.get("study")
        if isinstance(value, str) and value.startswith("atlas://study/"):
            return value
        try:
            relative = path.relative_to(self.root / "studies")
        except ValueError:
            return None
        if len(relative.parts) < 2:
            return None
        identifier_match = re.match(r"^(S\d{3})-", relative.parts[0])
        version_match = re.match(r"^v(\d+)$", relative.parts[1])
        if identifier_match and version_match:
            return f"atlas://study/{identifier_match.group(1)}@v{int(version_match.group(1))}"
        return None

    def _edges(self, entities: dict[str, Entity]) -> list[dict[str, Any]]:
        specs: list[EdgeSpec] = []
        for entity in entities.values():
            specs.extend(self._artifact_edges(entity, entities))
            citations = entity.artifact.get("citations", [])
            if isinstance(citations, list):
                specs.extend(
                    EdgeSpec(
                        entity.reference,
                        target,
                        "CITES",
                        assertion_level="theoretical",
                        source_path=entity.node["source_path"],
                    )
                    for target in citations
                    if isinstance(target, str)
                )
        edges = []
        seen = set()
        for spec in specs:
            if spec.source not in entities or spec.target not in entities:
                continue
            edge = self._edge(spec)
            if edge["id"] in seen:
                continue
            self._guard_edge(edge)
            edges.append(edge)
            seen.add(edge["id"])
        return edges

    def _spec(
        self,
        entity: Entity,
        target: str,
        relation: str,
        *,
        assertion_level: str = "structural",
        evidence: tuple[str, ...] = (),
        scope: dict[str, Any] | None = None,
        confidence: str = "none",
    ) -> EdgeSpec:
        return EdgeSpec(
            entity.reference,
            target,
            relation,
            assertion_level,
            evidence,
            scope,
            confidence,
            entity.node["source_path"],
        )

    def _artifact_edges(self, entity: Entity, entities: dict[str, Entity]) -> list[EdgeSpec]:
        data = entity.artifact
        kind = str(data.get("kind", ""))
        output: list[EdgeSpec] = []
        mappings = {
            "characteristics": "HAS_CHARACTERISTIC",
            "system_pressures": "ASSOCIATED_WITH",
            "candidate_optimizations": "SUGGESTS",
            "target_bottlenecks": "TARGETS",
            "applicable_characteristics": "APPLIES_UNDER",
            "background_sources": "CITES",
            "mechanism_sources": "CITES",
            "sources": "CITES",
        }
        for key, relation in mappings.items():
            values = data.get(key, [])
            if not isinstance(values, list):
                continue
            assertion = "theoretical" if relation == "CITES" else "structural"
            output.extend(
                self._spec(entity, value, relation, assertion_level=assertion)
                for value in values
                if isinstance(value, str)
            )

        if kind == "Study":
            output.append(self._spec(entity, data["archetype"], "INSTANCE_OF"))
            contracts = data.get("contracts", {})
            for key, relation in (
                ("workload", "USES_CONFIGURATION"),
                ("quality", "HAS_QUALITY_CONTRACT"),
                ("slo", "HAS_SLO"),
            ):
                if isinstance(contracts.get(key), str):
                    output.append(self._spec(entity, contracts[key], relation))
            for key, relation in (
                ("models", "USES_MODEL"),
                ("hardware", "EXECUTED_ON"),
                ("runtimes", "USES_RUNTIME"),
            ):
                for target in data.get("candidate_space", {}).get(key, []):
                    output.append(self._spec(entity, target, relation))
        elif kind == "WorkloadSpec":
            if isinstance(data.get("archetype"), str):
                output.append(self._spec(entity, data["archetype"], "INSTANCE_OF"))
            if isinstance(data.get("traffic"), str):
                output.append(self._spec(entity, data["traffic"], "USES_TRAFFIC_REGIME"))
            if isinstance(data.get("quality_contract"), str):
                output.append(self._spec(entity, data["quality_contract"], "HAS_QUALITY_CONTRACT"))
            if isinstance(data.get("slo"), str):
                output.append(self._spec(entity, data["slo"], "HAS_SLO"))
        elif kind == "Configuration":
            for key, relation in (
                ("workload", "USES_CONFIGURATION"),
                ("quality", "HAS_QUALITY_CONTRACT"),
                ("slo", "HAS_SLO"),
                ("model", "USES_MODEL"),
                ("hardware", "EXECUTED_ON"),
                ("runtime", "USES_RUNTIME"),
                ("runtime_configuration", "USES_CONFIGURATION"),
            ):
                output.append(self._spec(entity, data[key], relation))
        elif kind == "Experiment":
            output.append(
                EdgeSpec(
                    data["study"],
                    entity.reference,
                    "PRODUCES",
                    source_path=entity.node["source_path"],
                )
            )
            output.append(
                self._spec(
                    entity,
                    data["hypothesis"],
                    "TESTS",
                    assertion_level="hypothetical",
                )
            )
            output.append(self._spec(entity, data["baseline"], "USES_CONFIGURATION"))
            output.extend(
                self._spec(entity, target, "USES_CONFIGURATION") for target in data["candidates"]
            )
        elif kind == "RunRecord":
            output.append(
                EdgeSpec(
                    data["experiment"],
                    entity.reference,
                    "HAS_RUN",
                    evidence=(entity.reference,),
                    source_path=entity.node["source_path"],
                )
            )
            output.append(self._spec(entity, data["configuration"], "USES_CONFIGURATION"))
        elif kind == "Comparison":
            output.append(
                EdgeSpec(
                    data["experiment"],
                    entity.reference,
                    "PRODUCES",
                    source_path=entity.node["source_path"],
                )
            )
            output.extend(
                self._spec(entity, target, "COMPARES") for target in data["baseline_runs"]
            )
            output.extend(
                self._spec(entity, target, "COMPARES") for target in data["candidate_runs"]
            )
            result_relation = {
                "improvement": "IMPROVES",
                "degradation": "DEGRADES",
                "no_significant_effect": "NO_SIGNIFICANT_EFFECT",
            }.get(data["result"])
            if result_relation:
                targets = {
                    entities[run_reference].artifact["configuration"]
                    for run_reference in data["candidate_runs"]
                    if run_reference in entities
                }
                output.extend(
                    self._spec(
                        entity,
                        target,
                        result_relation,
                        assertion_level="experimentally_supported",
                        evidence=(entity.reference,),
                        confidence="moderate",
                    )
                    for target in targets
                )
        elif kind == "Finding":
            relation = "CONTRADICTS" if data["claim_status"] == "contradicted" else "SUPPORTS"
            for target in data["evidence"]["comparisons"]:
                output.append(
                    EdgeSpec(
                        target,
                        entity.reference,
                        relation,
                        assertion_level="experimentally_supported",
                        evidence=(target,),
                        scope=data.get("scope", {}),
                        confidence=data.get("evidence_confidence", "low"),
                        source_path=entity.node["source_path"],
                    )
                )
        elif kind == "DeploymentDecision":
            output.append(
                EdgeSpec(
                    data["study"],
                    entity.reference,
                    "PRODUCES",
                    source_path=entity.node["source_path"],
                )
            )
            if isinstance(data.get("selected_configuration"), str):
                output.append(
                    self._spec(entity, data["selected_configuration"], "USES_CONFIGURATION")
                )
            for target in data.get("supporting_findings", []):
                output.append(
                    EdgeSpec(
                        target,
                        entity.reference,
                        "JUSTIFIES",
                        assertion_level="experimentally_supported",
                        evidence=(target,),
                        source_path=entity.node["source_path"],
                    )
                )
            for item in data.get("rejected_alternatives", []):
                output.append(self._spec(entity, item["configuration"], "REJECTS"))
        elif kind == "Replication":
            output.append(
                self._spec(
                    entity,
                    data["finding"],
                    "REPLICATES",
                    assertion_level="replicated",
                    evidence=(entity.reference,),
                    confidence="moderate",
                )
            )

        interactions = data.get("interactions", {})
        if isinstance(interactions, dict):
            output.extend(
                self._spec(
                    entity,
                    target,
                    "INTERACTS_WITH",
                    assertion_level="theoretical",
                )
                for target in interactions.get("synergizes_with", [])
            )
            output.extend(
                self._spec(entity, target, "LIMITED_BY", assertion_level="theoretical")
                for target in interactions.get("conflicts_with", [])
            )
        return output

    def _edge(self, spec: EdgeSpec) -> dict[str, Any]:
        identity = canonical_json(
            [spec.source, spec.relation, spec.target, spec.source_path, list(spec.evidence)]
        )
        digest = hashlib.sha256(identity.encode()).hexdigest()[:16]
        return {
            "id": f"edge-{digest}",
            "source": spec.source,
            "target": spec.target,
            "relation": spec.relation,
            "assertion_level": spec.assertion_level,
            "evidence": sorted(spec.evidence),
            "scope": spec.scope or {},
            "confidence": spec.confidence,
            "provenance": {"source_path": spec.source_path, "derived": spec.derived},
        }

    def _guard_edge(self, edge: dict[str, Any]) -> None:
        if edge["relation"] in CAUSAL_RELATIONS:
            if edge["assertion_level"] not in {"experimentally_supported", "replicated"}:
                raise GraphError(f"Causal edge lacks experimental assertion: {edge['id']}")
            if not edge["evidence"]:
                raise GraphError(f"Causal edge lacks Atlas evidence: {edge['id']}")
        if edge["relation"] == "CITES" and edge["assertion_level"] not in {
            "structural",
            "theoretical",
        }:
            raise GraphError(f"Source citation was promoted beyond theory: {edge['id']}")

    def _schema_id(self, name: str) -> str:
        suffix = f"/graph/{name}.schema.json"
        return next(
            identifier for identifier in self.catalog.identifiers if identifier.endswith(suffix)
        )

    def _validate_graph(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
        node_schema = self._schema_id("graph-node")
        edge_schema = self._schema_id("graph-edge")
        errors: list[str] = []
        for node in nodes:
            errors.extend(
                f"{node['id']}{error.path}: {error.message}"
                for error in self.catalog.validate(node, node_schema)
            )
        for edge in edges:
            errors.extend(
                f"{edge['id']}{error.path}: {error.message}"
                for error in self.catalog.validate(edge, edge_schema)
            )
        node_ids = {node["id"] for node in nodes}
        for edge in edges:
            if edge["source"] not in node_ids or edge["target"] not in node_ids:
                errors.append(f"{edge['id']}: unresolved node")
        if errors:
            raise GraphError("Graph validation failed: " + "; ".join(errors))

    def _write_projection(
        self,
        output: Path,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        entities: dict[str, Entity],
        scope: dict[str, str],
    ) -> None:
        output.mkdir(parents=True, exist_ok=True)
        dump_json({"graph_version": 1, "nodes": nodes, "edges": edges}, output / "graph.json")
        indexes = self._indexes(nodes, edges)
        self._validate_object(indexes, "graph-indexes")
        dump_json(indexes, output / "indexes.json")
        views = compile_views(nodes, edges, scope)
        view_root = output / "views"
        for identifier, view in views.items():
            self._validate_object(view, "graph-view")
            dump_json(view, view_root / f"{identifier}.json")

        incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
        outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            incoming[edge["target"]].append(edge)
            outgoing[edge["source"]].append(edge)
        entity_root = output / "entities"
        for reference in sorted(node["id"] for node in nodes):
            entity = entities[reference]
            detail = {
                "node": entity.node,
                "artifact": entity.artifact,
                "incoming": sorted(incoming[reference], key=lambda item: item["id"]),
                "outgoing": sorted(outgoing[reference], key=lambda item: item["id"]),
                "referenced_by": indexes["referenced_by"].get(reference, []),
            }
            self._validate_object(detail, "entity-detail")
            dump_json(detail, entity_root / Path(entity.node["detail_path"]).name)

        revision, generated_at = self._revision()
        manifest = {
            "graph_version": 1,
            "generated_at": generated_at,
            "repository_commit": revision,
            "scope": scope,
            "counts": {"nodes": len(nodes), "edges": len(edges), "entities": len(nodes)},
            "files": {
                "graph": "graph.json",
                "indexes": "indexes.json",
                "views": [f"views/{identifier}.json" for identifier in sorted(views)],
            },
        }
        self._validate_object(manifest, "graph-manifest")
        dump_json(manifest, output / "manifest.json")

    def _validate_object(self, value: dict[str, Any], schema_name: str) -> None:
        errors = self.catalog.validate(value, self._schema_id(schema_name))
        if errors:
            rendered = "; ".join(f"{error.path}: {error.message}" for error in errors)
            raise GraphError(f"{schema_name} validation failed: {rendered}")

    def _indexes(
        self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> dict[str, dict[str, list[str]]]:
        indexes: dict[str, dict[str, list[str]]] = {
            "by_type": defaultdict(list),
            "by_status": defaultdict(list),
            "by_study": defaultdict(list),
            "by_tag": defaultdict(list),
            "referenced_by": defaultdict(list),
        }
        for node in nodes:
            indexes["by_type"][node["type"]].append(node["id"])
            indexes["by_status"][node["status"]].append(node["id"])
            if node.get("study"):
                indexes["by_study"][node["study"]].append(node["id"])
            for tag in node["tags"]:
                indexes["by_tag"][tag].append(node["id"])
        for edge in edges:
            indexes["referenced_by"][edge["target"]].append(edge["source"])
        return {
            name: {key: sorted(set(values)) for key, values in sorted(index.items())}
            for name, index in indexes.items()
        }

    def _study_projection(
        self,
        study_reference: str,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        included = {
            node["id"]
            for node in nodes
            if node["id"] == study_reference or node.get("study") == study_reference
        }
        for _ in range(3):
            included.update(edge["target"] for edge in edges if edge["source"] in included)
            included.update(
                edge["source"]
                for edge in edges
                if edge["target"] in included and edge["relation"] in {"SUPPORTS", "JUSTIFIES"}
            )
        selected_nodes = [node for node in nodes if node["id"] in included]
        selected_edges = [
            edge for edge in edges if edge["source"] in included and edge["target"] in included
        ]
        return selected_nodes, selected_edges

    def _study_directory(self, entity: Entity) -> str:
        try:
            relative = entity.path.relative_to(self.root / "studies")
            return relative.parts[0]
        except ValueError:
            return f"{entity.artifact['id']}-{entity.artifact['slug']}"

    def _revision(self) -> tuple[str, str]:
        revision = self._git("rev-parse", "HEAD") or "unknown"
        if self._git("status", "--porcelain"):
            revision += "-dirty"
        commit_time = self._git("show", "-s", "--format=%cI", "HEAD")
        if commit_time:
            parsed = datetime.fromisoformat(commit_time.replace("Z", "+00:00"))
            generated = (
                parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            )
        else:
            generated = "1970-01-01T00:00:00Z"
        return revision, generated

    def _git(self, *arguments: str) -> str:
        result = subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
