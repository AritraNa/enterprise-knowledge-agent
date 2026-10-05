from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from app.graph.repository import IngestionJobRepository
from app.graph.repository import EmployeeRepository
from app.ingestion.excel_parser import parse_employees
from app.models.ingestion_job import IngestionJob
from app.retrieval.employee_vector_store import EmployeeVectorStore


class EmployeeImporter:
    def __init__(
        self,
        repository: EmployeeRepository,
        job_repository: IngestionJobRepository,
        vector_store: EmployeeVectorStore | None = None,
    ):
        self.repository = repository
        self.job_repository = job_repository
        self.vector_store = vector_store

    def import_file(self, path: str):
        job = IngestionJob(
            id=f"job_{uuid4()}",
            source_file=path,
            source_hash=sha256(Path(path).read_bytes()).hexdigest(),
            status="RUNNING",
            started_at=datetime.now(timezone.utc),
        )

        self.job_repository.create(job)

        records = parse_employees(path)

        for employee, source_record in records:
            self.repository.upsert_employee(
                employee,
                source_record,
                job,
            )

        self.repository.rebuild_reporting_lines()

        if self.vector_store:
            self.vector_store.upsert_employees(
                [employee for employee, _ in records]
            )

        job.status = "COMPLETED"
        job.completed_at = datetime.now(timezone.utc)
        self.job_repository.complete(job)

        return len(records)
