"""Backfill enriched employee graph fields for directories indexed before v2."""

from app.ingestion.normalizer import normalize_skills, parse_experience_years
from app.models.employee import Employee
from app.retrieval.employee_vector_store import EmployeeVectorStore


def backfill_employee_graph(store: EmployeeVectorStore) -> int:
    """Normalize existing employee properties, graph relations, and embeddings."""
    query = """
    MATCH (employee:Employee)
    OPTIONAL MATCH (employee)-[:WORKS_FOR]->(department:Department)
    RETURN employee.id AS id, employee.employee_id AS employee_id,
           employee.name AS name, employee.email AS email,
           employee.department_id AS department_id, department.name AS department_name,
           employee.job_title AS job_title, employee.location AS location,
           employee.manager_id AS manager_id, employee.skills AS skills,
           employee.experience_summary AS experience_summary, employee.salary AS salary
    """
    with store.driver.session() as session:
        records = session.run(query).data()

    employees = [
        Employee(
            id=row["id"],
            employee_id=row["employee_id"].removeprefix("emp_"),
            name=row["name"],
            email=row["email"],
            department_id=row["department_id"],
            department_name=row["department_name"] or row["department_id"],
            job_title=row["job_title"],
            location=row["location"],
            manager_id=row["manager_id"],
            skills=normalize_skills(",".join(row["skills"] or [])),
            experience_summary=row["experience_summary"],
            experience_years=parse_experience_years(row["experience_summary"]),
            salary=row["salary"],
        )
        for row in records
    ]
    if not employees:
        return 0

    rows = [
        {
            "id": employee.id,
            "skills": employee.skills,
            "experience_years": employee.experience_years,
        }
        for employee in employees
    ]
    with store.driver.session() as session:
        session.run(
            "UNWIND $rows AS row MATCH (employee:Employee {id: row.id}) "
            "SET employee.skills = row.skills, employee.experience_years = row.experience_years",
            rows=rows,
        ).consume()
        session.run(
            """
            OPTIONAL MATCH (:Employee)-[relationship:HAS_SKILL]->(:Skill)
            DELETE relationship
            WITH 1 AS ignored
            UNWIND $rows AS row
            MATCH (employee:Employee {id: row.id})
            UNWIND row.skills AS skill_name
            MERGE (skill:Skill {normalized_name: toLower(skill_name)})
            SET skill.name = skill_name
            MERGE (employee)-[:HAS_SKILL]->(skill)
            """,
            rows=rows,
        ).consume()
        session.run(
            """
            OPTIONAL MATCH (:Employee)-[relationship:REPORTS_TO]->(:Employee)
            DELETE relationship
            WITH 1 AS ignored
            MATCH (employee:Employee)
            WHERE employee.manager_id IS NOT NULL
            MATCH (manager:Employee {
                id: CASE WHEN employee.manager_id STARTS WITH 'emp_' THEN employee.manager_id
                         ELSE 'emp_' + employee.manager_id END
            })
            MERGE (employee)-[:REPORTS_TO]->(manager)
            """
        ).consume()

    store.upsert_employees(employees)
    return len(employees)
