from app.models.employee import Employee
from app.models.source_record import SourceRecord

from app.models.ingestion_job import IngestionJob


class EmployeeRepository:

    def __init__(self, driver):
        self.driver = driver

    def upsert_employee(
        self,
        employee: Employee,
        source_record: SourceRecord,
        job: IngestionJob,
    ):

        query = """
        MERGE (e:Employee {id: $employee_id})
        SET
            e.employee_id = $employee_id,
            e.name = $name,
            e.email = $email,
            e.department_id = $department_id,
            e.job_title = $job_title,
            e.location = $location,
            e.manager_id = $manager_id,
            e.skills = $skills,
            e.experience_summary = $experience_summary,
            e.salary = $salary

        MERGE (d:Department {id: $department_id})
        SET d.name = $department_name

        MERGE (e)-[:WORKS_FOR]->(d)

        MERGE (s:SourceRecord {id: $source_id})
        SET
            s.source_file = $source_file,
            s.sheet_name = $sheet_name,
            s.row_number = $row_number

        MERGE (j:IngestionJob {id: $job_id})
        MERGE (s)-[:PROCESSED_IN]->(j)
        MERGE (e)-[:DERIVED_FROM]->(s)

        RETURN e, d, s, j
        """

        with self.driver.session() as session:
            result = session.run(
                query,
                employee_id=employee.id,
                name=employee.name,
                email=str(employee.email) if employee.email else None,
                department_id=employee.department_id,
                department_name=employee.department_name,
                job_title=employee.job_title,
                location=employee.location,
                manager_id=employee.manager_id,
                skills=employee.skills,
                experience_summary=employee.experience_summary,
                source_id=source_record.id,
                source_file=source_record.source_file,
                sheet_name=source_record.sheet_name,
                row_number=source_record.row_number,
                salary=employee.salary,
                job_id=job.id,
            )

            return result.single()


class IngestionJobRepository:
    def __init__(self, driver):
        self.driver = driver

    def create(self, job: IngestionJob):
        query = """
        MERGE (j:IngestionJob {id: $id})
        SET j.source_file = $source_file,
            j.status = $status,
            j.started_at = $started_at,
            j.completed_at = $completed_at
        RETURN j
        """

        with self.driver.session() as session:
            result = session.run(
                query,
                id=job.id,
                source_file=job.source_file,
                status=job.status,
                started_at=job.started_at.isoformat(),
                completed_at=(
                    job.completed_at.isoformat() if job.completed_at else None
                ),
            )

            return result.single()
