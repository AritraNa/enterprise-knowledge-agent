import argparse
import os
from hashlib import sha256
from pathlib import Path

from dotenv import load_dotenv

from .graph.neo4j_client import Neo4jStore
from .graph.repository import EmployeeRepository, IngestionJobRepository
from .ingestion.employee_importer import EmployeeImporter
from .ingestion.employee_graph_migration import backfill_employee_graph
from .ingestion.policy_pdf_importer import PolicyPDFImporter
from .retrieval.employee_vector_store import EmployeeVectorStore
from .retrieval.policy_vector_store import PolicyVectorStore
from .workflows.policy_rag import PolicyRAGWorkflow


def ingest(source_file: str) -> None:
    """Import the spreadsheet into Neo4j and refresh employee embeddings."""
    store = Neo4jStore()

    try:
        store.verify()
        store.init_schema()

        importer = EmployeeImporter(
            EmployeeRepository(store.driver),
            IngestionJobRepository(store.driver),
            EmployeeVectorStore(driver=store.driver),
        )
        count = importer.import_file(source_file)
        print(f"Imported {count} employees into Neo4j and its vector index.")
    finally:
        store.close()


def search(query: str, limit: int) -> None:
    """Print employee matches from Neo4j's vector index."""
    results = EmployeeVectorStore().search_with_scores(query, limit)

    if not results:
        print("No matching employee documents found. Run ingest first.")
        return

    for position, (document, score) in enumerate(results, start=1):
        employee_id = document.metadata["employee_id"]
        print(f"\n{position}. {employee_id} (similarity: {score:.4f})")
        print(document.page_content)


def migrate_employee_graph() -> None:
    """Upgrade existing employee records with relationship and filter metadata."""
    store = EmployeeVectorStore()
    try:
        count = backfill_employee_graph(store)
        print(f"Upgraded {count} employee records with skills and reporting relationships.")
    finally:
        store.driver.close()


def ingest_policy(source_file: str) -> None:
    """Extract, section, chunk, and index a policy PDF."""
    chunks = PolicyPDFImporter().load(source_file)
    source_hash = sha256(Path(source_file).read_bytes()).hexdigest()
    PolicyVectorStore().replace_source(
        chunks,
        source_hash=source_hash,
        policy_type="General",
    )
    print(f"Indexed {len(chunks)} chunks from {source_file}.")


def search_policy(query: str, limit: int) -> None:
    """Print source-backed policy evidence from Neo4j's vector index."""
    results = PolicyVectorStore().search_with_scores(query, limit)

    if not results:
        print("No policy index or matching evidence found. Run ingest-policy first.")
        return

    for position, (document, score) in enumerate(results, start=1):
        metadata = document.metadata
        print(f"\nEvidence {position} (similarity: {score:.4f})")
        print(f"Source document: {metadata['source_document']}")
        print(f"Section: {metadata['section']}")
        print(f"Page: {metadata['page']}")
        print("Evidence:")
        print(document.page_content)


def ask_policy(question: str, limit: int) -> None:
    """Run the LangGraph grounded-answer workflow for a policy question."""
    result = PolicyRAGWorkflow().ask(question, limit)
    print("Answer:")
    print(result["answer"])

    citations = result["citations"]
    if citations:
        print("\nSources:")
        for citation in citations:
            print(
                f"[{citation['citation_id']}] {citation['source_document']} | "
                f"{citation['section']} | page {citation['page']}"
            )


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Ingest and semantically search enterprise employee data."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    ingest_command = commands.add_parser("ingest", help="Import Excel into Neo4j")
    ingest_command.add_argument(
        "--source",
        default="data/raw/employees.xlsx",
        help="Path to the employee Excel file",
    )

    search_command = commands.add_parser("search", help="Search Neo4j employee vectors")
    search_command.add_argument("query", help="Natural-language employee search query")
    search_command.add_argument(
        "--limit",
        type=int,
        default=int(os.getenv("RETRIEVAL_TOP_K", "5")),
        help="Maximum number of employees to return",
    )

    employee_migration_command = commands.add_parser(
        "migrate-employee-graph", help="Backfill skills, experience, and reporting links"
    )

    policy_ingest_command = commands.add_parser(
        "ingest-policy", help="Extract and index a policy PDF into Neo4j"
    )
    policy_ingest_command.add_argument(
        "source_file", help="Path to a policy PDF, for example data/raw/policies/hr.pdf"
    )

    policy_search_command = commands.add_parser(
        "search-policy", help="Search policy evidence in Neo4j with citations"
    )
    policy_search_command.add_argument("query", help="Natural-language policy question")
    policy_search_command.add_argument(
        "--limit",
        type=int,
        default=int(os.getenv("RETRIEVAL_TOP_K", "5")),
        help="Maximum number of evidence chunks to return",
    )

    policy_answer_command = commands.add_parser(
        "ask-policy", help="Answer a policy question with LangGraph and citations"
    )
    policy_answer_command.add_argument(
        "question", help="Natural-language policy question"
    )
    policy_answer_command.add_argument(
        "--limit",
        type=int,
        default=int(os.getenv("RETRIEVAL_TOP_K", "5")),
        help="Maximum number of evidence chunks to provide to the model",
    )

    args = parser.parse_args()
    if args.command == "ingest":
        ingest(args.source)
    elif args.command == "search":
        search(args.query, args.limit)
    elif args.command == "migrate-employee-graph":
        migrate_employee_graph()
    elif args.command == "ingest-policy":
        ingest_policy(args.source_file)
    elif args.command == "search-policy":
        search_policy(args.query, args.limit)
    else:
        ask_policy(args.question, args.limit)


if __name__ == "__main__":
    main()
