"""Run the policy retrieval regression dataset against Neo4j.

Usage:
    uv run python -m app.evaluation.policy_retrieval
"""

import json
from pathlib import Path

from dotenv import load_dotenv

from app.retrieval.policy_vector_store import PolicyVectorStore


DATASET_PATH = Path("data/evals/policy_retrieval.json")


def evaluate(dataset_path: Path = DATASET_PATH, limit: int = 3) -> bool:
    """Print retrieval regressions and return whether every case passed."""
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    store = PolicyVectorStore()
    passed = 0
    try:
        for case in cases:
            results = store.search_with_scores(
                case["question"],
                limit=limit,
                filters={
                    "policy_type": case["expected_policy_type"],
                    "status": "active",
                },
            )
            evidence = " ".join(document.page_content.casefold() for document, _ in results)
            terms = [term.casefold() for term in case["expected_evidence_terms"]]
            has_expected_terms = all(term in evidence for term in terms)
            case_passed = bool(results) and has_expected_terms
            passed += case_passed
            status = "PASS" if case_passed else "FAIL"
            print(f"{status}: {case['question']}")
            if results:
                document, score = results[0]
                print(
                    f"  top result: {document.metadata['source_document']} "
                    f"({score:.3f})"
                )
            else:
                print("  no matching policy evidence")
    finally:
        store.driver.close()

    print(f"\n{passed}/{len(cases)} retrieval cases passed")
    return passed == len(cases)


if __name__ == "__main__":
    load_dotenv()
    raise SystemExit(0 if evaluate() else 1)
