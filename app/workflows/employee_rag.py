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

    def ask(
        self, question: str, limit: int = 5, filters: dict[str, str | None] | None = None
    ) -> PolicyRAGState:
        """Route structured employee analytics to Neo4j, otherwise run RAG."""
        filters = filters or {}
        intent = self._analytics_intent(question)
        if intent:
            if not filters.get("include_sensitive"):
                return self._respond_insufficient({"sensitive_access_denied": True})
            return self._run_salary_analytics(intent)
        return super().ask(question, limit, filters)

    @staticmethod
    def _analytics_intent(question: str) -> dict[str, float | str] | None:
        """Recognize numeric salary analytics that embeddings should not answer."""
        if not re.search(r"\b(average|mean)\b", question, re.I) or not re.search(
            r"\b(salary|compensation|pay|ctc|lpa|wage)\b", question, re.I
        ):
            return None
        patterns = (
            (r"\b(?:more than|over|greater than)\s+(\d+(?:\.\d+)?)\s*(?:years?|yrs?)", ">"),
            (r"\b(?:at least|minimum of)\s+(\d+(?:\.\d+)?)\s*(?:years?|yrs?)", ">="),
            (r"\b(?:less than|under)\s+(\d+(?:\.\d+)?)\s*(?:years?|yrs?)", "<"),
            (r"\b(?:at most|maximum of)\s+(\d+(?:\.\d+)?)\s*(?:years?|yrs?)", "<="),
        )
        for pattern, operator in patterns:
            if match := re.search(pattern, question, re.I):
                return {"operator": operator, "experience_years": float(match.group(1))}
        return None

    def _run_salary_analytics(self, intent: dict[str, float | str]) -> PolicyRAGState:
        operator = str(intent["operator"])
        years = float(intent["experience_years"])
        query = f"""
        MATCH (employee:Employee)
        WHERE employee.experience_years {operator} $experience_years
          AND employee.salary_lpa IS NOT NULL
        RETURN employee.id AS employee_id, employee.name AS name,
               employee.experience_years AS experience_years,
               employee.salary_lpa AS salary_lpa
        ORDER BY employee.name
        """
        with self.vector_store.driver.session() as session:
            rows = session.run(query, experience_years=years).data()

        evidence: list[Evidence] = []
        for citation_id, row in enumerate(rows, start=1):
            evidence.append(
                {
                    "citation_id": citation_id,
                    "source_document": "Employee directory",
                    "section": f"Employee record: {row['name']} ({row['employee_id']})",
                    "page": 0,
                    "content": (
                        f"Employee: {row['name']}\n"
                        f"Experience years: {row['experience_years']}\n"
                        f"Salary: {row['salary_lpa']} LPA"
                    ),
                    "score": 1.0,
                }
            )
        if not evidence:
            return {
                "answer": "No employee records have both a salary and the requested experience range.",
                "citations": [],
            }

        average = sum(float(row["salary_lpa"]) for row in rows) / len(rows)
        comparison = f"{operator} {years:g} years"
        source_list = ", ".join(
            f"{row['name']} ({row['salary_lpa']:g} LPA) [{index}]"
            for index, row in enumerate(rows, start=1)
        )
        return {
            "answer": (
                f"The average salary for employees with experience {comparison} is "
                f"{average:.2f} LPA, based on {len(rows)} employees: {source_list}."
            ),
            "citations": evidence,
        }

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
                    "You are an enterprise employee-directory assistant. "
                    "Answer only from the provided employee records. Do not add or infer facts, skills, roles, reporting relationships, compensation, or contact details that are not supported by the records. "
                    "You may perform calculations and aggregations using values explicitly present in the provided records when the user's question requires them. This includes average, sum, total, minimum, maximum, count, difference, percentage, grouping, and comparison. "
                    "When performing a calculation, use only values explicitly present in the provided employee records and include every record matching the user's requested criteria. Do not silently exclude matching records or estimate, infer, or substitute missing values. "
                    "If required values are missing, clearly state that the calculation cannot be completed accurately from the available evidence. "
                    "Show the relevant values used in the calculation when useful for verification. Clearly distinguish calculated results from values directly stated in the records. "
                    "Cite every factual statement using evidence numbers such as [1] or [1][2]. For calculated values, cite the evidence containing all underlying values used in the calculation. "
                    "If the records do not contain enough information to answer the question or perform the requested calculation reliably, say so. "
                    "For an authorized compensation question, include every matching employee record relevant to the requested calculation or result. Do not omit a matching record or claim a count unless the evidence establishes it.",
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
