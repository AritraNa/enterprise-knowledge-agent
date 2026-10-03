import argparse
import os

from dotenv import load_dotenv

from .graph.neo4j_client import Neo4jStore
from .graph.repository import EmployeeRepository, IngestionJobRepository
from .ingestion.employee_importer import EmployeeImporter
from .retrieval.employee_vector_store import EmployeeVectorStore


VECTOR_STORE_PATH = "data/vector_store/employees"


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

    args = parser.parse_args()
    if args.command == "ingest":
        ingest(args.source)
    else:
        search(args.query, args.limit)


if __name__ == "__main__":
    main()
