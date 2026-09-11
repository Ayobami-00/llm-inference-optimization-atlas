from __future__ import annotations

from atlas.studies.evaluators import (
    evaluate_chat_records,
    evaluate_code_results,
    evaluate_engram_equivalence,
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


def test_engram_evaluator_requires_exact_tokens_and_resolved_treatment() -> None:
    reference = [{"request_id": "q1", "outcome": "complete", "output_token_ids": [1, 2, 3]}]
    matching = [
        {
            "request_id": "q1",
            "outcome": "complete",
            "output_token_ids": [1, 2, 3],
            "finite": True,
        }
    ]
    assert evaluate_engram_equivalence(matching, reference)["passed"]

    matching[0]["unexpected_fallback"] = True
    result = evaluate_engram_equivalence(matching, reference)
    assert not result["passed"]
    assert result["dimensions"]["no_unexpected_fallback_rate"] == 0.0


def test_engram_evaluator_rejects_missing_or_changed_responses() -> None:
    reference = [
        {"request_id": "q1", "outcome": "complete", "output_token_ids": [1, 2, 3]},
        {"request_id": "q2", "outcome": "complete", "output_token_ids": [4, 5, 6]},
    ]
    candidate = [{"request_id": "q1", "outcome": "complete", "output_token_ids": [1, 9, 3]}]
    result = evaluate_engram_equivalence(candidate, reference)
    assert not result["passed"]
    assert result["dimensions"]["request_completion_rate"] == 0.5
    assert result["dimensions"]["exact_output_token_agreement"] == 0.0
