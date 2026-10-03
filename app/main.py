import argparse
import os

from dotenv import load_dotenv

from .graph.neo4j_client import Neo4jStore
from .graph.repository import EmployeeRepository, IngestionJobRepository
from .ingestion.employee_importer import EmployeeImporter
from .ingestion.policy_pdf_importer import PolicyPDFImporter
from .retrieval.employee_vector_store import EmployeeVectorStore
from .retrieval.policy_vector_store import PolicyVectorStore
from .workflows.policy_rag import PolicyRAGWorkflow


VECTOR_STORE_PATH = "data/vector_store/employees"
POLICY_VECTOR_STORE_PATH = "data/vector_store/policies"


def ingest(source_file: str) -> None:
    """Import the spreadsheet into Neo4j and refresh the FAISS index."""
    store = Neo4jStore()

    try:
        store.verify()
        store.init_schema()

        importer = EmployeeImporter(
            EmployeeRepository(store.driver),
            IngestionJobRepository(store.driver),
            EmployeeVectorStore(VECTOR_STORE_PATH),
        )
        count = importer.import_file(source_file)
        print(f"Imported {count} employees into Neo4j and FAISS.")
    finally:
        store.close()


def search(query: str, limit: int) -> None:
    """Print employee matches from the persisted FAISS index."""
    results = EmployeeVectorStore(VECTOR_STORE_PATH).search_with_scores(query, limit)

    if not results:
        print("No FAISS index or matching employee documents found. Run ingest first.")
        return

    for position, (document, distance) in enumerate(results, start=1):
        employee_id = document.metadata["employee_id"]
        print(f"\n{position}. {employee_id} (FAISS distance: {distance:.4f})")
        print(document.page_content)


def ingest_policy(source_file: str) -> None:
    """Extract, section, chunk, and index a policy PDF."""
    chunks = PolicyPDFImporter().load(source_file)
    PolicyVectorStore(POLICY_VECTOR_STORE_PATH).replace_source(chunks)
    print(f"Indexed {len(chunks)} chunks from {source_file}.")


def search_policy(query: str, limit: int) -> None:
    """Print source-backed policy evidence from the local FAISS index."""
    results = PolicyVectorStore(POLICY_VECTOR_STORE_PATH).search_with_scores(
        query, limit
    )

    if not results:
        print("No policy index or matching evidence found. Run ingest-policy first.")
        return

    for position, (document, distance) in enumerate(results, start=1):
        metadata = document.metadata
        print(f"\nEvidence {position} (FAISS distance: {distance:.4f})")
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

    ingest_command = commands.add_parser("ingest", help="Import Excel into Neo4j and FAISS")
    ingest_command.add_argument(
        "--source",
        default="data/raw/employees.xlsx",
        help="Path to the employee Excel file",
    )

    search_command = commands.add_parser("search", help="Search the local FAISS index")
    search_command.add_argument("query", help="Natural-language employee search query")
    search_command.add_argument(
        "--limit",
        type=int,
        default=int(os.getenv("RETRIEVAL_TOP_K", "5")),
        help="Maximum number of employees to return",
    )

    policy_ingest_command = commands.add_parser(
        "ingest-policy", help="Extract and index a policy PDF into FAISS"
    )
    policy_ingest_command.add_argument(
        "source_file", help="Path to a policy PDF, for example data/raw/policies/hr.pdf"
    )

    policy_search_command = commands.add_parser(
        "search-policy", help="Search the local policy FAISS index with citations"
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
    elif args.command == "ingest-policy":
        ingest_policy(args.source_file)
    elif args.command == "search-policy":
        search_policy(args.query, args.limit)
    else:
        ask_policy(args.question, args.limit)


if __name__ == "__main__":
    main()
