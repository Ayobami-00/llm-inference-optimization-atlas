from __future__ import annotations

import re
from statistics import fmean
from typing import Any


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def keyword_recall(text: str, expected: list[str]) -> float:
    if not expected:
        return 1.0
    normalized = _normalized(text)
    found = sum(_normalized(value) in normalized for value in expected)
    return found / len(expected)


def evaluate_chat_records(
    responses: list[dict[str, Any]], records: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    details = []
    for response in responses:
        record = records[str(response["request_id"])]
        text = str(response.get("text", "")).strip()
        valid = bool(text) and not response.get("error")
        recall = keyword_recall(text, list(record.get("expected_keywords", []))) if valid else 0.0
        details.append(
            {
                "request_id": response["request_id"],
                "valid_output": valid,
                "topic_keyword_recall": recall,
            }
        )
    valid_rate = fmean(float(item["valid_output"]) for item in details) if details else 0.0
    topic_recall = fmean(item["topic_keyword_recall"] for item in details) if details else 0.0
    return {
        "gate": "Q1",
        "passed": valid_rate == 1.0 and topic_recall >= 0.75,
        "dimensions": {"valid_output": valid_rate, "topic_keyword_recall": topic_recall},
        "details": details,
    }


FENCED_CODE = re.compile(r"```(?:python)?\s*(?P<code>.*?)```", re.DOTALL | re.IGNORECASE)


def extract_python(text: str, function_name: str) -> str:
    match = FENCED_CODE.search(text)
    code = match.group("code").strip() if match else text.strip()
    marker = f"def {function_name}("
    index = code.find(marker)
    if index < 0:
        return code
    return code[index:]


def evaluate_code_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    safe = all(bool(item.get("sandbox_completed")) for item in results)
    pass_rate = (
        fmean(float(bool(item.get("tests_passed"))) for item in results) if results else 0.0
    )
    return {
        "gate": "Q1",
        "passed": safe and pass_rate >= 1 / 3,
        "dimensions": {
            "sandbox_completion": float(safe),
            "unit_test_pass_rate": pass_rate,
        },
        "details": results,
    }


def _citations(text: str) -> set[str]:
    return set(re.findall(r"\bDOC[0-9]{3}\b", text.upper()))


def evaluate_rag_records(responses: list[dict[str, Any]]) -> dict[str, Any]:
    details = []
    for response in responses:
        relevant = set(response.get("relevant_docs", []))
        retrieved = set(response.get("retrieved_docs", []))
        cited = _citations(str(response.get("text", "")))
        retrieval_recall = len(relevant & retrieved) / len(relevant) if relevant else 1.0
        answer_recall = keyword_recall(
            str(response.get("text", "")), list(response.get("answer_keywords", []))
        )
        citation_precision = len(cited & relevant) / len(cited) if cited else 0.0
        citation_recall = len(cited & relevant) / len(relevant) if relevant else 1.0
        format_passed = bool(re.search(r"(?im)^sources?:", str(response.get("text", ""))))
        details.append(
            {
                "request_id": response["request_id"],
                "retrieval_recall": retrieval_recall,
                "answer_keyword_recall": answer_recall,
                "citation_precision": citation_precision,
                "citation_recall": citation_recall,
                "format_passed": format_passed,
            }
        )

    def average(name: str) -> float:
        return fmean(float(item[name]) for item in details) if details else 0.0

    dimensions = {
        "retrieval_recall": average("retrieval_recall"),
        "answer_keyword_recall": average("answer_keyword_recall"),
        "citation_precision": average("citation_precision"),
        "citation_recall": average("citation_recall"),
        "format_pass_rate": average("format_passed"),
    }
    return {
        "gate": "Q1",
        "passed": (
            dimensions["retrieval_recall"] >= 0.9
            and dimensions["answer_keyword_recall"] >= 0.7
            and dimensions["citation_precision"] >= 0.8
            and dimensions["format_pass_rate"] == 1.0
        ),
        "dimensions": dimensions,
        "details": details,
    }
