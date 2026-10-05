import os
import re

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
        if self._requests_sensitive_data(state["question"]) and not state.get(
            "filters", {}
        ).get("include_sensitive"):
            return {"evidence": [], "sensitive_access_denied": True}
        include_sensitive = bool(state.get("filters", {}).get("include_sensitive"))
        results = self.vector_store.search_with_scores(
            state["question"],
            state.get("limit", 5),
            filters=state.get("filters"),
            include_sensitive=include_sensitive,
        )
        evidence: list[Evidence] = []

        for citation_id, (document, score) in enumerate(results, start=1):
            evidence.append(self._employee_evidence(document, score, citation_id))
        print({"_retrieve_evidence": evidence})
        return {"evidence": evidence}

    @staticmethod
    def _requests_sensitive_data(question: str) -> bool:
        return bool(
            re.search(r"\b(salary|compensation|pay|ctc|lpa|wage)\b", question, re.I)
        )

    @staticmethod
    def _respond_insufficient(state: PolicyRAGState) -> PolicyRAGState:
        if state.get("sensitive_access_denied"):
            return {
                "answer": (
                    "Compensation data is restricted. An authorized HR request must "
                    "include the configured X-API-Key header."
                ),
                "citations": [],
            }
        return PolicyRAGWorkflow._respond_insufficient(state)

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
                    "numbers such as [1] or [1][2]. For an authorized compensation "
                    "question, list the salary from every matching employee record; "
                    "do not summarize, omit a matching record, or claim a count "
                    "unless the evidence establishes it.",
                ),
                (
                    "human",
                    f"Question: {state['question']}\n\n"
                    f"Employee records:\n{self._format_evidence(evidence)}",
                ),
            ]
        )
        answer = str(response.content).strip()
        cited_ids = {int(value) for value in self._citation_pattern.findall(answer)}
        citations = [item for item in evidence if item["citation_id"] in cited_ids]
        # A source list is still returned when a model omits inline [1] markers.
        # This keeps the answer usable while preserving the retrieved evidence.
        return {"answer": answer, "citations": citations or evidence}
