from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

from app.models.employee import Employee
from app.retrieval.embedding_utils import (
    create_embeddings,
    rebuild_if_embedding_config_changed,
    save_store,
)

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def employee_to_document(employee: Employee) -> Document:
    """Represent an employee as text while retaining filterable metadata."""
    lines = [
        f"Employee: {employee.name}",
        f"Department: {employee.department_name}",
    ]

    if employee.job_title:
        lines.append(f"Job title: {employee.job_title}")
    if employee.location:
        lines.append(f"Location: {employee.location}")
    if employee.skills:
        lines.append(f"Skills: {', '.join(employee.skills)}")
    if employee.experience_summary:
        lines.append(f"Experience: {employee.experience_summary}")
    if employee.salary:
        lines.append(f"Salary: {employee.salary}")

    return Document(
        id=employee.id,
        page_content="\n".join(lines),
        metadata={
            "employee_id": employee.id,
            "department_id": employee.department_id,
            "department": employee.department_name,
            "location": employee.location,
            "job_title": employee.job_title,
            "salary": employee.salary,
        },
    )


class EmployeeVectorStore:
    """Persist and update employee documents in a local FAISS index."""

    def __init__(
        self,
        index_path: str | Path,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    ):
        self.index_path = Path(index_path)
        self.embedding_model = embedding_model
        self._embeddings: HuggingFaceEmbeddings | None = None
        self._store: FAISS | None = None

    @property
    def embeddings(self) -> HuggingFaceEmbeddings:
        """Load the model only when the index is first used."""
        if self._embeddings is None:
            self._embeddings = create_embeddings(self.embedding_model)
        return self._embeddings

    def upsert_employees(self, employees: list[Employee]) -> None:
        if not employees:
            return

        documents = [employee_to_document(employee) for employee in employees]
        ids = [employee.id for employee in employees]
        store = self._load()

        if store is None:
            self._store = FAISS.from_documents(documents, self.embeddings, ids=ids)
        else:
            existing_ids = set(store.index_to_docstore_id.values())
            ids_to_replace = list(existing_ids.intersection(ids))
            if ids_to_replace:
                store.delete(ids_to_replace)
            store.add_documents(documents, ids=ids)

        save_store(self.index_path, self._store)

    def search(self, query: str, limit: int = 5) -> list[Document]:
        store = self._load()
        if store is None:
            return []
        return store.similarity_search(query, k=limit)

    def search_with_scores(
        self, query: str, limit: int = 5
    ) -> list[tuple[Document, float]]:
        """Return matching employee documents and their FAISS distances.

        A lower distance means the document is a closer semantic match.
        """
        store = self._load()
        if store is None:
            return []
        candidate_limit = min(store.index.ntotal, max(limit, 50))
        results = store.similarity_search_with_score(query, k=candidate_limit)
        exact_skill_matches = [
            result for result in results if self._matches_listed_skill(query, result[0])
        ]
        semantic_matches = [
            result for result in results if result not in exact_skill_matches
        ]
        return (exact_skill_matches + semantic_matches)[:limit]

    def _load(self) -> FAISS | None:
        if self._store is not None:
            return self._store

        if not (self.index_path / "index.faiss").exists():
            return None

        # This index is produced only by this application. Do not load indexes
        # obtained from untrusted sources.
        loaded_store = FAISS.load_local(
            str(self.index_path),
            self.embeddings,
            allow_dangerous_deserialization=True,
        )
        self._store = rebuild_if_embedding_config_changed(
            self.index_path, loaded_store, self.embeddings
        )
        return self._store

    @staticmethod
    def _matches_listed_skill(query: str, document: Document) -> bool:
        """Prefer exact skills for a skill-specific employee question."""
        query_text = query.casefold()
        for line in document.page_content.splitlines():
            if not line.startswith("Skills:"):
                continue
            skills = (skill.strip().casefold() for skill in line.removeprefix("Skills:").split(","))
            return any(skill and skill in query_text for skill in skills)
        return False
