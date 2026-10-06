import os
import re

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
            for employee, document, vector in zip(
                employees, documents, vectors, strict=True
            )
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
        self,
        query: str,
        limit: int = 5,
        filters: dict | None = None,
        include_sensitive: bool = False,
    ) -> list[tuple[Document, float]]:
        """Find employees using semantic relevance, keywords, and graph filters."""
        query_vector = self.embeddings.embed_query(query)
        filters = filters or {}
        # Only an explicit API `skills` filter is exact. Natural-language skill
        # phrases remain semantic so related skills can still be retrieved.
        requested_skills = [skill.casefold() for skill in filters.get("skills", [])]
        experience_operator, experience_years = self._experience_constraint(
            query, filters
        )
        experience_predicate = (
            f"employee.experience_years {experience_operator} $experience_years"
            if experience_operator
            else "$experience_years IS NULL"
        )
        candidate_limit = max(limit * 5, 25)
        vector_cypher = """
        MATCH (employee:Employee)
        SEARCH employee IN (
            VECTOR INDEX employee_embedding_index
            FOR $embedding
            LIMIT $limit
        ) SCORE AS score
        OPTIONAL MATCH (employee)-[:WORKS_FOR]->(department:Department)
        WITH employee, department, score
        WHERE ($department IS NULL OR toLower(department.name) = toLower($department))
          AND ($location IS NULL OR toLower(employee.location) = toLower($location))
          AND ($job_title IS NULL OR toLower(employee.job_title) = toLower($job_title))
          AND ({experience_predicate})
          AND (size($skills) = 0 OR ALL(skill_name IN $skills WHERE EXISTS {
              MATCH (employee)-[:HAS_SKILL]->(:Skill {normalized_name: skill_name})
          } OR skill_name IN [listed_skill IN coalesce(employee.skills, []) | toLower(listed_skill)]))
        RETURN employee.id AS employee_id, employee.department_id AS department_id,
               department.name AS department, employee.location AS location,
               employee.job_title AS job_title, employee.salary AS salary,
               employee.salary_lpa AS salary_lpa, employee.skills AS skills,
               employee.experience_years AS experience_years,
               employee.search_content AS content, score
        """
        keyword_cypher = """
        CALL db.index.fulltext.queryNodes('employee_directory_fulltext', $search_text)
        YIELD node AS employee, score
        OPTIONAL MATCH (employee)-[:WORKS_FOR]->(department:Department)
        WITH employee, department, score
        WHERE ($department IS NULL OR toLower(department.name) = toLower($department))
          AND ($location IS NULL OR toLower(employee.location) = toLower($location))
          AND ($job_title IS NULL OR toLower(employee.job_title) = toLower($job_title))
          AND ({experience_predicate})
          AND (size($skills) = 0 OR ALL(skill_name IN $skills WHERE EXISTS {
              MATCH (employee)-[:HAS_SKILL]->(:Skill {normalized_name: skill_name})
          } OR skill_name IN [listed_skill IN coalesce(employee.skills, []) | toLower(listed_skill)]))
        RETURN employee.id AS employee_id, employee.department_id AS department_id,
               department.name AS department, employee.location AS location,
               employee.job_title AS job_title, employee.salary AS salary,
               employee.salary_lpa AS salary_lpa, employee.skills AS skills,
               employee.experience_years AS experience_years,
               employee.search_content AS content, score
        LIMIT $limit
        """
        vector_cypher = vector_cypher.replace(
            "{experience_predicate}", experience_predicate
        )
        keyword_cypher = keyword_cypher.replace(
            "{experience_predicate}", experience_predicate
        )
        parameters = {
            "embedding": query_vector,
            "limit": candidate_limit,
            "search_text": self._keyword_query(query),
            "department": filters.get("department"),
            "location": filters.get("location"),
            "job_title": filters.get("job_title"),
            "experience_years": experience_years,
            "skills": requested_skills,
        }
        with self.driver.session() as session:
            vector_records = session.run(vector_cypher, **parameters).data()
            keyword_records = session.run(keyword_cypher, **parameters).data()

        merged = {
            record["employee_id"]: {**record, "vector_score": float(record["score"])}
            for record in vector_records
            if record["content"]
        }
        max_keyword_score = max(
            (float(row["score"]) for row in keyword_records), default=1.0
        )
        for record in keyword_records:
            if not record["content"]:
                continue
            candidate = merged.setdefault(
                record["employee_id"], {**record, "vector_score": 0.0}
            )
            candidate["keyword_score"] = float(record["score"]) / max_keyword_score

        results = []
        for record in merged.values():
            score = 0.80 * max(record["vector_score"], 0.0) + 0.20 * record.get(
                "keyword_score", 0.0
            )
            document = self._to_document(record, include_sensitive)
            if self._matches_listed_skill(query, document):
                score += 0.10
            results.append((document, min(score, 1.0)))
        return sorted(results, key=lambda result: result[1], reverse=True)[:limit]

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
            session.run(
                "CREATE FULLTEXT INDEX employee_directory_fulltext IF NOT EXISTS "
                "FOR (employee:Employee) ON EACH "
                "[employee.name, employee.employee_id, employee.job_title, "
                "employee.location, employee.search_content]"
            ).consume()

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

    @staticmethod
    def _keyword_query(query: str) -> str:
        stop_words = {
            "a",
            "an",
            "does",
            "has",
            "have",
            "in",
            "is",
            "the",
            "who",
            "with",
        }
        terms = [
            term
            for term in re.findall(r"[A-Za-z0-9]+", query.casefold())
            if term not in stop_words
        ]
        return " OR ".join(terms) or query

    @staticmethod
    def _experience_constraint(
        query: str, filters: dict
    ) -> tuple[str | None, float | None]:
        """Translate common comparative experience phrases into exact filters."""
        if filters.get("min_experience_years") is not None:
            return ">=", float(filters["min_experience_years"])
        patterns = (
            (
                r"\b(?:more than|over|greater than)\s+(\d+(?:\.\d+)?)\s*(?:years?|yrs?)",
                ">",
            ),
            (r"\b(?:at least|minimum of)\s+(\d+(?:\.\d+)?)\s*(?:years?|yrs?)", ">="),
            (r"\b(?:less than|under)\s+(\d+(?:\.\d+)?)\s*(?:years?|yrs?)", "<"),
            (r"\b(?:at most|maximum of)\s+(\d+(?:\.\d+)?)\s*(?:years?|yrs?)", "<="),
        )
        for pattern, operator in patterns:
            if match := re.search(pattern, query, re.I):
                return operator, float(match.group(1))
        return None, None

    @staticmethod
    def _to_document(record: dict, include_sensitive: bool) -> Document:
        metadata = {
            "employee_id": record["employee_id"],
            "department_id": record["department_id"],
            "department": record["department"],
            "location": record["location"],
            "job_title": record["job_title"],
            "skills": record["skills"] or [],
            "experience_years": record["experience_years"],
        }
        if include_sensitive:
            metadata["salary"] = record["salary"]
            metadata["salary_lpa"] = record["salary_lpa"]
        content = record["content"]
        if include_sensitive and record["salary_lpa"] is not None:
            content = f"{content}\nSalary: {record['salary_lpa']:g} LPA"
        elif include_sensitive and record["salary"]:
            content = f"{content}\nSalary: {record['salary']}"
        return Document(page_content=content, metadata=metadata)


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
    return Document(
        id=employee.id,
        page_content="\n".join(lines),
        metadata={
            "employee_id": employee.id,
            "department_id": employee.department_id,
            "department": employee.department_name,
            "location": employee.location,
            "job_title": employee.job_title,
            "skills": employee.skills,
            "experience_years": employee.experience_years,
        },
    )
