from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from atlas.contributions import contribution_status, start_contribution
from atlas.identities import next_identifiers
from atlas.utilities.serialization import yaml_writer
from atlas.validation import Validator

ROOT = Path(__file__).parents[2]
ISSUE_URL = "https://github.com/Ayobami-00/llm-inference-optimization-atlas/issues/23"


def _issue() -> dict[str, Any]:
    return {
        "number": 23,
        "body": """<!-- atlas-proposal-form:v1:study -->
### Proposal title

CPU long-context prompt reuse

### Summary

Measure prompt reuse for repeated long-document questions on CPU.

### Motivation

The practical TTFT effect is not established on the target hardware.

### Scope

```yaml
study_id: S004
slug: cpu-long-context-prompt-reuse
archetype: atlas://workload/W004@v1
traffic_regimes:
  - atlas://traffic/T001@v1
models:
  - atlas://model/M001@v1
hardware:
  - atlas://hardware/HW001@v1
runtimes:
  - atlas://runtime/RT001@v1
research_questions:
  - Does prompt reuse reduce server TTFT without failing Q1?
included:
  - Repeated long-document questions
excluded:
  - GPU execution
```

### Planned artifacts

```yaml
- study
- workload
- experiments
- findings
- decision
```

### Resources

```yaml
compute: Local CPU for two hours
downloads: 300 MB model
```

### Risks

```yaml
- Findings may transfer only to the measured hardware.
```

### Conflict disclosure

None declared
""",
        "labels": [
            {"name": "proposal:type:study"},
            {"name": "proposal:approved"},
        ],
        "user": {"login": "contributor"},
        "created_at": "2026-08-29T08:00:00Z",
        "updated_at": "2026-08-29T09:00:00Z",
        "html_url": ISSUE_URL,
    }


def _copy_reference_system(tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    shutil.copytree(ROOT / "reference" / "schemas", reference / "schemas")
    shutil.copytree(ROOT / "reference" / "templates", reference / "templates")
    shutil.copytree(ROOT / "reference" / "ontology", reference / "ontology")
    shutil.copytree(ROOT / "registry", tmp_path / "registry")


def test_contribution_start_materializes_and_scaffolds_an_approved_study(
    tmp_path: Path,
) -> None:
    _copy_reference_system(tmp_path)

    result = start_contribution(tmp_path, ISSUE_URL, fetcher=lambda _: _issue())

    study_root = tmp_path / result.contribution_path
    assert result.proposal_id == "P0023"
    assert result.proposal_path == ".atlas/work/proposals/P0023.yaml"
    assert result.expected_branch == "feat/23-cpu-long-context-prompt-reuse"
    assert study_root == tmp_path / "studies/S004-cpu-long-context-prompt-reuse/v1"
    assert (study_root / "workload.yaml").is_file()
    assert (study_root / "quality.yaml").is_file()
    assert (study_root / "slo.yaml").is_file()

    status = contribution_status(tmp_path, "S004")
    assert not status.ready
    assert status.stages[0].complete
    assert not status.stages[1].complete
    assert status.validation_errors == 0
    assert "workload.yaml" in status.next_action


def test_next_identifiers_are_consecutive_after_the_highest_existing_id(
    tmp_path: Path,
) -> None:
    records = tmp_path / "records"
    records.mkdir()
    for identifier in ("E0002", "E0007"):
        with (records / f"{identifier}.yaml").open("w") as stream:
            yaml_writer().dump({"id": identifier}, stream)

    assert next_identifiers(tmp_path, "experiment", count=3) == [
        "E0008",
        "E0009",
        "E0010",
    ]


def test_all_contribution_templates_validate_against_v1_schemas() -> None:
    report = Validator(ROOT).validate_path(
        ROOT / "reference" / "templates" / "v1",
        include_templates=True,
    )

    assert report.ok, report.as_dict()
