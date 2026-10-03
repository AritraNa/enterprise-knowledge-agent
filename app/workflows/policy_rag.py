import os
import re
from typing import Literal, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from app.retrieval.policy_vector_store import PolicyVectorStore


class Evidence(TypedDict):
    citation_id: int
    source_document: str
    section: str
    page: int
    content: str
    distance: float


class PolicyRAGState(TypedDict, total=False):
    question: str
    limit: int
    evidence: list[Evidence]
    evidence_sufficient: bool
    answer: str
    citations: list[Evidence]


class PolicyRAGWorkflow:
    """A grounded LangGraph workflow for answering policy questions."""

    def __init__(
        self,
        vector_store: PolicyVectorStore | None = None,
        chat_model: ChatOpenAI | None = None,
        max_evidence_distance: float | None = None,
    ):
        self.vector_store = vector_store or PolicyVectorStore(
            "data/vector_store/policies"
        )
        self.chat_model = chat_model
        self.max_evidence_distance = (
            max_evidence_distance
            if max_evidence_distance is not None
            else float(os.getenv("RAG_MAX_FAISS_DISTANCE", "1.25"))
        )
        self.graph = self._build_graph()

    def ask(self, question: str, limit: int = 5) -> PolicyRAGState:
        """Run retrieval, evidence validation, and grounded answer generation."""
        return self.graph.invoke({"question": question, "limit": limit})

    def _build_graph(self):
        builder = StateGraph(PolicyRAGState)
        builder.add_node("retrieve_evidence", self._retrieve_evidence)
        builder.add_node("validate_evidence", self._validate_evidence)
        builder.add_node("generate_answer", self._generate_answer)
        builder.add_node("respond_insufficient", self._respond_insufficient)

        builder.add_edge(START, "retrieve_evidence")
        builder.add_edge("retrieve_evidence", "validate_evidence")
        builder.add_conditional_edges(
            "validate_evidence",
            self._route_after_validation,
            {
                "generate_answer": "generate_answer",
                "respond_insufficient": "respond_insufficient",
            },
        )
        builder.add_edge("generate_answer", END)
        builder.add_edge("respond_insufficient", END)
        return builder.compile()

    def _retrieve_evidence(self, state: PolicyRAGState) -> PolicyRAGState:
        results = self.vector_store.search_with_scores(
            state["question"], state.get("limit", 5)
        )
        evidence: list[Evidence] = []

        for citation_id, (document, distance) in enumerate(results, start=1):
            metadata = document.metadata
            evidence.append(
                {
                    "citation_id": citation_id,
                    "source_document": metadata["source_document"],
                    "section": metadata["section"],
                    "page": metadata["page"],
                    "content": document.page_content,
                    "distance": float(distance),
                }
            )

        return {"evidence": evidence}

    def _validate_evidence(self, state: PolicyRAGState) -> PolicyRAGState:
        """Refuse to generate when no retrieval result is relevant enough."""
        evidence = state.get("evidence", [])
        best_distance = min((item["distance"] for item in evidence), default=float("inf"))
        return {
            "evidence_sufficient": bool(evidence)
            and best_distance <= self.max_evidence_distance
        }

    @staticmethod
    def _route_after_validation(
        state: PolicyRAGState,
    ) -> Literal["generate_answer", "respond_insufficient"]:
        if state["evidence_sufficient"]:
            return "generate_answer"
        return "respond_insufficient"

    def _generate_answer(self, state: PolicyRAGState) -> PolicyRAGState:
        evidence = state["evidence"]
        response = self._model().invoke(
            [
                (
                    "system",
                    "You are an enterprise policy assistant. Answer only from the "
                    "provided evidence. Do not add facts, advice, or sources that "
                    "are not in it. If the evidence does not directly answer the "
                    "question, say so. Do not assign a responsibility to a person, "
                    "team, or department unless the evidence explicitly names that "
                    "entity with that responsibility. Cite every factual statement "
                    "using one or more evidence numbers such as [1] or [1][2].",
                ),
                (
                    "human",
                    f"Question: {state['question']}\n\n"
                    f"Evidence:\n{self._format_evidence(evidence)}",
                ),
            ]
        )
        answer = str(response.content).strip()
        cited_ids = {int(value) for value in re.findall(r"\[(\d+)\]", answer)}
        citations = [
            item for item in evidence if item["citation_id"] in cited_ids
        ]

        # Preserve provenance even if a local model omits the requested markers.
        return {"answer": answer, "citations": citations or evidence}

    @staticmethod
    def _respond_insufficient(_: PolicyRAGState) -> PolicyRAGState:
        return {
            "answer": (
                "I could not find sufficiently relevant, source-backed evidence for "
                "that question in the indexed policy documents."
            ),
            "citations": [],
        }

    def _model(self) -> ChatOpenAI:
        if self.chat_model is not None:
            return self.chat_model

        base_url = os.getenv("OLLAMA_BASE_URL")
        model = os.getenv("DOCUMENT_INGESTION_MODEL")
        if not base_url or not model:
            raise RuntimeError(
                "Set OLLAMA_BASE_URL and DOCUMENT_INGESTION_MODEL in .env before "
                "running ask-policy."
            )

        self.chat_model = ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
            temperature=0,
        )
        return self.chat_model

    @staticmethod
    def _format_evidence(evidence: list[Evidence]) -> str:
        return "\n\n".join(
            (
                f"[{item['citation_id']}] Source: {item['source_document']} | "
                f"Section: {item['section']} | Page: {item['page']}\n"
                f"{item['content']}"
            )
            for item in evidence
        )
