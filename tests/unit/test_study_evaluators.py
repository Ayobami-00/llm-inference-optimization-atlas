from __future__ import annotations

from atlas.studies.evaluators import (
    evaluate_chat_records,
    evaluate_code_results,
    evaluate_rag_records,
    extract_python,
)


def test_chat_evaluator_applies_frozen_keywords() -> None:
    result = evaluate_chat_records(
        [{"request_id": "one", "text": "Spinach and egg toast."}],
        {"one": {"expected_keywords": ["spinach", "egg"]}},
    )
    assert result["passed"]


def test_code_extraction_and_result_gate() -> None:
    assert extract_python("```python\ndef add(a, b):\n    return a + b\n```", "add").startswith(
        "def add"
    )
    assert evaluate_code_results(
        [
            {"sandbox_completed": True, "tests_passed": True},
            {"sandbox_completed": True, "tests_passed": False},
            {"sandbox_completed": True, "tests_passed": False},
        ]
    )["passed"]


def test_rag_evaluator_checks_retrieval_answer_and_citation() -> None:
    result = evaluate_rag_records(
        [
            {
                "request_id": "q1",
                "text": "The link lasts 20 minutes.\nSources: DOC001",
                "relevant_docs": ["DOC001"],
                "retrieved_docs": ["DOC001", "DOC009"],
                "answer_keywords": ["20 minutes"],
            }
        ]
    )
    assert result["passed"]
