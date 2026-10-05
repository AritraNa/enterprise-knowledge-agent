"""Run employee retrieval regression cases against Neo4j."""

import json
from pathlib import Path

from dotenv import load_dotenv

from app.retrieval.employee_vector_store import EmployeeVectorStore


DATASET_PATH = Path("data/evals/employee_retrieval.json")


def evaluate(dataset_path: Path = DATASET_PATH, limit: int = 5) -> bool:
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    store = EmployeeVectorStore()
    passed = 0
    try:
        for case in cases:
            results = store.search_with_scores(
                case["question"], limit, filters=case.get("filters")
            )
            actual_ids = {document.metadata["employee_id"] for document, _ in results}
            expected_ids = set(case["expected_employee_ids"])
            case_passed = expected_ids.issubset(actual_ids)
            passed += case_passed
            print(f"{'PASS' if case_passed else 'FAIL'}: {case['question']}")
            print(f"  expected: {sorted(expected_ids)}; actual: {sorted(actual_ids)}")
    finally:
        store.driver.close()

    print(f"\n{passed}/{len(cases)} employee retrieval cases passed")
    return passed == len(cases)


if __name__ == "__main__":
    load_dotenv()
    raise SystemExit(0 if evaluate() else 1)
