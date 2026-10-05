import os

from langchain_core.documents import Document

from app.retrieval.employee_vector_store import EmployeeVectorStore
from app.workflows.policy_rag import Evidence, PolicyRAGState, PolicyRAGWorkflow


class EmployeeRAGWorkflow(PolicyRAGWorkflow):
    """Grounded LangGraph answers over indexed employee records."""

    def __init__(self, vector_store: EmployeeVectorStore | None = None, **kwargs):
        kwargs.setdefault(
            "min_similarity_score",
            float(os.getenv("RAG_MIN_EMPLOYEE_SIMILARITY_SCORE", "0.4")),
        )
        super().__init__(
            vector_store=vector_store or EmployeeVectorStore(),
            **kwargs,
        )

    def _retrieve_evidence(self, state: PolicyRAGState) -> PolicyRAGState:
        results = self.vector_store.search_with_scores(
            state["question"], state.get("limit", 5)
        )
        evidence: list[Evidence] = []

        for citation_id, (document, score) in enumerate(results, start=1):
            evidence.append(self._employee_evidence(document, score, citation_id))

        return {"evidence": evidence}

    @staticmethod
    def _employee_evidence(
        document: Document, score: float, citation_id: int
    ) -> Evidence:
        metadata = document.metadata
        name = document.page_content.splitlines()[0].removeprefix("Employee: ")
        employee_id = metadata["employee_id"]
        return {
            "citation_id": citation_id,
            "source_document": "Employee directory",
            "section": f"Employee record: {name} ({employee_id})",
            "page": 0,
            "content": document.page_content,
            "score": float(score),
        }

    def _generate_answer(self, state: PolicyRAGState) -> PolicyRAGState:
        evidence = state["evidence"]
        response = self._model().invoke(
            [
                (
                    "system",
                    "You are an enterprise employee-directory assistant. Answer only "
                    "from the provided employee records. Do not add facts, skills, "
                    "roles, reporting relationships, or contact details that are not "
                    "in the records. If the records do not directly answer the "
                    "question, say so. Cite every factual statement using evidence "
                    "numbers such as [1] or [1][2].",
                ),
                (
                    "human",
                    f"Question: {state['question']}\n\n"
                    f"Employee records:\n{self._format_evidence(evidence)}",
                ),
            ]
        )
        answer = str(response.content).strip()
        cited_ids = {
            int(value) for value in self._citation_pattern.findall(answer)
        }
        citations = [
            item for item in evidence if item["citation_id"] in cited_ids
        ]
        return {"answer": answer, "citations": citations or evidence}
