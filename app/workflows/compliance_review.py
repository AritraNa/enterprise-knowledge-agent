import os
import re
from collections.abc import Iterable
from typing import TypedDict

from langchain_core.documents import Document
from langchain_openai import ChatOpenAI

from app.retrieval.policy_vector_store import PolicyVectorStore


class ComplianceEvidence(TypedDict):
    citation_id: int
    source_document: str
    section: str
    page: int
    content: str
    score: float


class ComplianceReviewWorkflow:
    """Compare an uploaded document with the policies already indexed in Neo4j."""

    def __init__(
        self,
        vector_store: PolicyVectorStore | None = None,
        chat_model: ChatOpenAI | None = None,
    ) -> None:
        self.vector_store = vector_store or PolicyVectorStore()
        self.chat_model = chat_model

    def review(
        self, document_name: str, candidate_chunks: list[Document], instructions: str = ""
    ) -> dict:
        if not candidate_chunks:
            return {
                "assessment": "I could not extract reviewable text from the uploaded document.",
                "citations": [],
            }

        evidence = self._retrieve_policy_evidence(candidate_chunks)
        if not evidence:
            return {
                "assessment": (
                    "I could not find relevant indexed policy evidence to compare with "
                    f"{document_name}. Upload the governing policies first, then try again."
                ),
                "citations": [],
            }

        response = self._model().invoke(
            [
                (
                    "system",
                    """You are a compliance reviewer. Compare the uploaded document to the
provided policy evidence only. Produce a concise review with these headings:
Overall assessment, Matches, Gaps or conflicts, and Recommended follow-up.
For each finding, say what the uploaded document states (or does not state),
then explain how that relates to the policy. Do not invent requirements or
claim that a document is legally compliant. Every assertion about a policy
must cite one or more evidence numbers such as [1]. If the evidence cannot
support a conclusion, explicitly say that it needs human review.""",
                ),
                (
                    "human",
                    f"Uploaded document: {document_name}\n"
                    f"Review focus: {instructions or 'General policy compliance'}\n\n"
                    f"Uploaded document text:\n{self._format_candidate(candidate_chunks)}\n\n"
                    f"Indexed policy evidence:\n{self._format_evidence(evidence)}",
                ),
            ]
        )
        assessment = str(response.content).strip()
        cited_ids = {int(value) for value in re.findall(r"\[(\d+)\]", assessment)}
        return {
            "assessment": assessment,
            "citations": [item for item in evidence if item["citation_id"] in cited_ids],
        }

    def _retrieve_policy_evidence(
        self, candidate_chunks: Iterable[Document]
    ) -> list[ComplianceEvidence]:
        # Each uploaded section is used as a retrieval query, so a document with
        # several topics is compared against the right policy areas instead of
        # being represented by one broad query.
        selected: dict[tuple[str, str, int, str], tuple[Document, float]] = {}
        for chunk in list(candidate_chunks)[:20]:
            for policy, score in self.vector_store.search_with_scores(
                chunk.page_content, limit=3, filters={"status": "active"}
            ):
                key = (
                    policy.metadata["source_document"],
                    policy.metadata["section"],
                    policy.metadata["page"],
                    policy.page_content,
                )
                existing = selected.get(key)
                if existing is None or score > existing[1]:
                    selected[key] = (policy, score)

        ranked = sorted(selected.values(), key=lambda item: item[1], reverse=True)[:15]
        return [
            {
                "citation_id": citation_id,
                "source_document": document.metadata["source_document"],
                "section": document.metadata["section"],
                "page": document.metadata["page"],
                "content": document.page_content,
                "score": float(score),
            }
            for citation_id, (document, score) in enumerate(ranked, start=1)
        ]

    def _model(self) -> ChatOpenAI:
        if self.chat_model is None:
            base_url = os.getenv("OLLAMA_BASE_URL")
            model = os.getenv("DOCUMENT_INGESTION_MODEL")
            if not base_url or not model:
                raise RuntimeError(
                    "Set OLLAMA_BASE_URL and DOCUMENT_INGESTION_MODEL in .env before reviewing a document."
                )
            self.chat_model = ChatOpenAI(
                model=model,
                base_url=base_url,
                api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
                temperature=0,
            )
        return self.chat_model

    @staticmethod
    def _format_candidate(chunks: list[Document]) -> str:
        # Keep the prompt bounded while retaining section/page traceability.
        parts: list[str] = []
        remaining = 18_000
        for chunk in chunks:
            prefix = f"Page {chunk.metadata['page']} — {chunk.metadata['section']}\n"
            content = chunk.page_content[: max(0, remaining - len(prefix))]
            if not content:
                break
            parts.append(prefix + content)
            remaining -= len(prefix) + len(content)
            if remaining <= 0:
                break
        return "\n\n".join(parts)

    @staticmethod
    def _format_evidence(evidence: list[ComplianceEvidence]) -> str:
        return "\n\n".join(
            f"[{item['citation_id']}] Source: {item['source_document']} | "
            f"Section: {item['section']} | Page: {item['page']}\n{item['content']}"
            for item in evidence
        )
