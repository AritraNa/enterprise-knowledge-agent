from dotenv import load_dotenv

load_dotenv()

from .graph.neo4j_client import Neo4jStore
from .graph.repository import EmployeeRepository
from .graph.repository import IngestionJobRepository
from .ingestion.employee_importer import EmployeeImporter
from .retrieval.employee_vector_store import EmployeeVectorStore

store = Neo4jStore()

try:
    store.verify()
    store.init_schema()

    repository = EmployeeRepository(store.driver)
    job_repository = IngestionJobRepository(store.driver)
    vector_store = EmployeeVectorStore("data/vector_store/employees")

    importer = EmployeeImporter(repository, job_repository, vector_store)

    count = importer.import_file("data/raw/employees.xlsx")

    print(f"Imported {count} employees")

finally:
    store.close()
