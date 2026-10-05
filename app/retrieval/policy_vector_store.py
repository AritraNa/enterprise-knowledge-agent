import hashlib
import os
import re
from datetime import UTC, datetime

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from neo4j import GraphDatabase

from app.retrieval.embedding_utils import create_embeddings


class PolicyVectorStore:
    """Persistent policy retrieval backed by a Neo4j vector index."""

    INDEX_NAME = "policy_chunk_embedding_index"
    INDEX_LABEL = "PolicyChunk"
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

    def replace_source(
        self,
        chunks: list[Document],
        *,
        source_hash: str,
        policy_type: str = "General",
        owner_department: str | None = None,
        effective_date: str | None = None,
        version: str | None = None,
    ) -> None:
        """Persist a versioned policy document, sections, and chunks."""
        if not chunks:
            return

        source_document = chunks[0].metadata["source_document"]
        document_id = f"policy_{source_hash}"
        self._upsert_document(
            document_id,
            source_hash,
            source_document,
            policy_type,
            owner_department,
            effective_date,
            version or source_hash[:12],
        )
        vectors = self.embeddings.embed_documents(
            [chunk.page_content for chunk in chunks]
        )
        rows = [
            {
                "id": self._document_id(document_id, chunk),
                "document_id": document_id,
                "section_id": self._section_id(document_id, chunk),
                "content": chunk.page_content,
                "metadata": chunk.metadata,
                "embedding": vector,
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        query = """
        UNWIND $rows AS row
        MATCH (document:PolicyDocument {id: row.document_id})
        MERGE (section:PolicySection {id: row.section_id})
        SET section.title = row.metadata.section, section.page = row.metadata.page
        MERGE (document)-[:HAS_SECTION]->(section)
        MERGE (chunk:PolicyChunk {id: row.id})
        SET chunk.content = row.content, chunk.document_id = row.document_id,
            chunk.source_id = row.metadata.source_id, chunk.source_document = row.metadata.source_document,
            chunk.source_path = row.metadata.source_path, chunk.page = row.metadata.page,
            chunk.section = row.metadata.section, chunk.start_index = row.metadata.start_index,
            chunk.chunk_number = row.metadata.chunk_number, chunk.status = 'active',
            chunk.embedding = row.embedding
        MERGE (section)-[:HAS_CHUNK]->(chunk)
        """
        with self.driver.session() as session:
            session.run(query, rows=rows).consume()

    def search_with_scores(
        self, query: str, limit: int = 5, filters: dict | None = None
    ) -> list[tuple[Document, float]]:
        """Retrieve policy chunks with semantic + keyword ranking.

        Metadata constraints are applied in Neo4j before candidates are ranked.
        This keeps an active policy-type query from being crowded out by chunks
        belonging to unrelated or superseded documents.
        """
        query_vector = self.embeddings.embed_query(query)
        filters = {"status": "active", **(filters or {})}
        candidate_limit = max(limit * 5, 20)
        vector_cypher = """
        MATCH (chunk:PolicyChunk)
        SEARCH chunk IN (
            VECTOR INDEX policy_chunk_embedding_index
            FOR $embedding
            LIMIT $limit
        ) SCORE AS score
        MATCH (document:PolicyDocument)-[:HAS_SECTION]->(:PolicySection)-[:HAS_CHUNK]->(chunk)
        WHERE ($policy_type IS NULL OR document.policy_type = $policy_type)
          AND ($owner_department IS NULL OR document.owner_department = $owner_department)
          AND ($effective_date IS NULL OR document.effective_date = $effective_date)
          AND ($status IS NULL OR document.status = $status)
        RETURN chunk.id AS id, chunk.content AS content,
               chunk.source_document AS source_document, chunk.source_id AS source_id,
               chunk.source_path AS source_path, chunk.page AS page,
               chunk.section AS section, chunk.start_index AS start_index,
               chunk.chunk_number AS chunk_number, document.policy_type AS policy_type,
               document.owner_department AS owner_department,
               document.effective_date AS effective_date, document.version AS version,
               document.status AS status, score
        """
        keyword_cypher = """
        CALL db.index.fulltext.queryNodes('policy_chunk_fulltext', $search_text)
        YIELD node AS chunk, score
        MATCH (document:PolicyDocument)-[:HAS_SECTION]->(:PolicySection)-[:HAS_CHUNK]->(chunk)
        WHERE ($policy_type IS NULL OR document.policy_type = $policy_type)
          AND ($owner_department IS NULL OR document.owner_department = $owner_department)
          AND ($effective_date IS NULL OR document.effective_date = $effective_date)
          AND ($status IS NULL OR document.status = $status)
        RETURN chunk.id AS id, chunk.content AS content,
               chunk.source_document AS source_document, chunk.source_id AS source_id,
               chunk.source_path AS source_path, chunk.page AS page,
               chunk.section AS section, chunk.start_index AS start_index,
               chunk.chunk_number AS chunk_number, document.policy_type AS policy_type,
               document.owner_department AS owner_department,
               document.effective_date AS effective_date, document.version AS version,
               document.status AS status, score
        LIMIT $limit
        """
        parameters = {
            "limit": candidate_limit,
            "embedding": query_vector,
            "search_text": self._keyword_query(query),
            "policy_type": filters.get("policy_type"),
            "owner_department": filters.get("owner_department"),
            "effective_date": filters.get("effective_date"),
            "status": filters.get("status"),
        }
        with self.driver.session() as session:
            vector_records = session.run(vector_cypher, **parameters).data()
            keyword_records = session.run(keyword_cypher, **parameters).data()

        # Semantic similarity is the primary signal; lexical relevance is a
        # boost for policy names, section headings, limits, and acronyms.
        merged: dict[str, dict] = {
            record["id"]: {**record, "vector_score": float(record["score"])}
            for record in vector_records
        }
        max_keyword_score = max(
            (float(record["score"]) for record in keyword_records), default=1.0
        )
        for record in keyword_records:
            item = merged.setdefault(record["id"], {**record, "vector_score": 0.0})
            item["keyword_score"] = float(record["score"]) / max_keyword_score

        ranked = []
        for record in merged.values():
            score = (0.80 * max(record["vector_score"], 0.0)) + (
                0.20 * record.get("keyword_score", 0.0)
            )
            document = Document(
                page_content=record["content"],
                metadata={
                    key: record[key]
                    for key in (
                        "source_document",
                        "source_id",
                        "source_path",
                        "page",
                        "section",
                        "start_index",
                        "chunk_number",
                        "policy_type",
                        "owner_department",
                        "effective_date",
                        "version",
                        "status",
                    )
                },
            )
            ranked.append((document, score))
        return sorted(ranked, key=lambda item: item[1], reverse=True)[:limit]

    def _ensure_vector_index(self) -> None:
        query = f"""
        CREATE VECTOR INDEX {self.INDEX_NAME} IF NOT EXISTS
        FOR (chunk:{self.INDEX_LABEL}) ON (chunk.{self.EMBEDDING_PROPERTY})
        OPTIONS {{indexConfig: {{
            `vector.dimensions`: {self.dimensions},
            `vector.similarity_function`: 'cosine'
        }}}}
        """
        with self.driver.session() as session:
            session.run(
                "CREATE CONSTRAINT policy_document_id IF NOT EXISTS "
                "FOR (document:PolicyDocument) REQUIRE document.id IS UNIQUE"
            ).consume()
            session.run(
                "CREATE CONSTRAINT policy_section_id IF NOT EXISTS "
                "FOR (section:PolicySection) REQUIRE section.id IS UNIQUE"
            ).consume()
            session.run(
                "CREATE CONSTRAINT policy_chunk_id IF NOT EXISTS "
                "FOR (chunk:PolicyChunk) REQUIRE chunk.id IS UNIQUE"
            ).consume()
            session.run(query).consume()
            session.run(
                "CREATE FULLTEXT INDEX policy_chunk_fulltext IF NOT EXISTS "
                "FOR (chunk:PolicyChunk) ON EACH [chunk.content, chunk.section, chunk.source_document]"
            ).consume()

    def _upsert_document(
        self,
        document_id: str,
        source_hash: str,
        source_document: str,
        policy_type: str,
        owner_department: str | None,
        effective_date: str | None,
        version: str,
    ) -> None:
        query = """
        MERGE (document:PolicyDocument {id: $document_id})
        ON CREATE SET document.created_at = $now
        SET document.source_hash = $source_hash, document.source_document = $source_document,
            document.policy_type = $policy_type, document.owner_department = $owner_department,
            document.effective_date = $effective_date, document.version = $version,
            document.status = 'active', document.updated_at = $now
        """
        with self.driver.session() as session:
            session.run(
                query,
                document_id=document_id,
                source_hash=source_hash,
                source_document=source_document,
                policy_type=policy_type,
                owner_department=owner_department,
                effective_date=effective_date,
                version=version,
                now=datetime.now(UTC).isoformat(),
            ).consume()
            session.run(
                """
                MATCH (previous:PolicyDocument {source_document: $source_document, status: 'active'})
                WHERE previous.id <> $document_id
                SET previous.status = 'superseded', previous.superseded_at = $now
                """,
                source_document=source_document,
                document_id=document_id,
                now=datetime.now(UTC).isoformat(),
            ).consume()

    @staticmethod
    def _document_id(document_id: str, chunk: Document) -> str:
        identity = "|".join(
            [
                document_id,
                chunk.metadata["source_id"],
                str(chunk.metadata["page"]),
                chunk.metadata["section"],
                str(chunk.metadata["chunk_number"]),
                chunk.page_content,
            ]
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    @staticmethod
    def _section_id(document_id: str, chunk: Document) -> str:
        identity = f"{document_id}|{chunk.metadata['page']}|{chunk.metadata['section']}"
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    @staticmethod
    def _keyword_query(query: str) -> str:
        """Create a safe full-text query without Lucene control characters."""
        stop_words = {
            "a",
            "an",
            "are",
            "for",
            "how",
            "is",
            "of",
            "the",
            "to",
            "what",
            "who",
        }
        terms = [
            term
            for term in re.findall(r"[A-Za-z0-9]+", query.casefold())
            if term not in stop_words
        ]
        return " OR ".join(terms) or query
