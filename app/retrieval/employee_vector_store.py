import os

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from neo4j import GraphDatabase

from app.models.employee import Employee
from app.retrieval.embedding_utils import create_embeddings


class EmployeeVectorStore:
    """Persistent employee retrieval backed by a Neo4j vector index."""

    INDEX_NAME = "employee_embedding_index"
    INDEX_LABEL = "Employee"
    EMBEDDING_PROPERTY = "embedding"

    def __init__(self, driver=None):
        self.driver = driver or GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
        )
        self.dimensions = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))
        self._embeddings: OpenAIEmbeddings | None = None
        self._ensure_vector_index()

    @property
    def embeddings(self) -> OpenAIEmbeddings:
        if self._embeddings is None:
            self._embeddings = create_embeddings()
        return self._embeddings

    def upsert_employees(self, employees: list[Employee]) -> None:
        if not employees:
            return

        documents = [employee_to_document(employee) for employee in employees]
        vectors = self.embeddings.embed_documents(
            [document.page_content for document in documents]
        )
        rows = [
            {"id": employee.id, "content": document.page_content, "embedding": vector}
            for employee, document, vector in zip(employees, documents, vectors, strict=True)
        ]
        query = """
        UNWIND $rows AS row
        MATCH (employee:Employee {id: row.id})
        SET employee.search_content = row.content,
            employee.embedding = row.embedding
        """
        with self.driver.session() as session:
            session.run(query, rows=rows).consume()

    def search_with_scores(
        self, query: str, limit: int = 5
    ) -> list[tuple[Document, float]]:
        query_vector = self.embeddings.embed_query(query)
        cypher = """
        MATCH (employee:Employee)
        SEARCH employee IN (
            VECTOR INDEX employee_embedding_index
            FOR $embedding
            LIMIT $limit
        ) SCORE AS score
        RETURN employee.id AS employee_id,
               employee.department_id AS department_id,
               employee.location AS location,
               employee.job_title AS job_title,
               employee.salary AS salary,
               employee.search_content AS content,
               score
        """
        with self.driver.session() as session:
            records = session.run(
                cypher,
                limit=max(limit, 50),
                embedding=query_vector,
            ).data()

        results = [
            (
                Document(
                    page_content=record["content"],
                    metadata={
                        "employee_id": record["employee_id"],
                        "department_id": record["department_id"],
                        "department": None,
                        "location": record["location"],
                        "job_title": record["job_title"],
                        "salary": record["salary"],
                    },
                ),
                float(record["score"]),
            )
            for record in records
            if record["content"]
        ]
        exact_skill_matches = [
            result for result in results if self._matches_listed_skill(query, result[0])
        ]
        semantic_matches = [
            result for result in results if result not in exact_skill_matches
        ]
        return (exact_skill_matches + semantic_matches)[:limit]

    def _ensure_vector_index(self) -> None:
        query = f"""
        CREATE VECTOR INDEX {self.INDEX_NAME} IF NOT EXISTS
        FOR (employee:{self.INDEX_LABEL}) ON (employee.{self.EMBEDDING_PROPERTY})
        OPTIONS {{indexConfig: {{
            `vector.dimensions`: {self.dimensions},
            `vector.similarity_function`: 'cosine'
        }}}}
        """
        with self.driver.session() as session:
            session.run(query).consume()

    @staticmethod
    def _matches_listed_skill(query: str, document: Document) -> bool:
        query_text = query.casefold()
        for line in document.page_content.splitlines():
            if line.startswith("Skills:"):
                skills = (
                    skill.strip().casefold()
                    for skill in line.removeprefix("Skills:").split(",")
                )
                return any(skill and skill in query_text for skill in skills)
        return False


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
