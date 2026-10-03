from neo4j import Driver


class EmployeeAPIRepository:

    def __init__(self, driver: Driver):
        self.driver = driver

    def find_by_name(self, name: str):
        query = """
        MATCH (e:Employee)-[:WORKS_FOR]->(d:Department)
        WHERE toLower(e.name) = toLower($name)

        RETURN
            e.id AS id,
            e.employee_id AS employee_id,
            e.name AS name,
            e.email AS email,
            d.id AS department_id,
            d.name AS department
        """

        with self.driver.session() as session:
            result = session.run(query, name=name)
            return result.single()

    def find_by_department(self, department: str):
        query = """
        MATCH (e:Employee)-[:WORKS_FOR]->(d:Department)
        WHERE toLower(d.name) = toLower($department)

        RETURN
            e.id AS id,
            e.employee_id AS employee_id,
            e.name AS name,
            e.email AS email,
            d.name AS department
        ORDER BY e.name
        """

        with self.driver.session() as session:
            return list(session.run(query, department=department))

    def get_source(self, employee_id: str):
        query = """
        MATCH (e:Employee {id: $employee_id})
              -[:DERIVED_FROM]->(s:SourceRecord)
              -[:PROCESSED_IN]->(j:IngestionJob)

        RETURN
            e.name AS employee,
            e.email AS email,
            s.source_file AS source_file,
            s.sheet_name AS sheet_name,
            s.row_number AS row_number,
            j.id AS ingestion_job
        """

        with self.driver.session() as session:
            return session.run(query, employee_id=employee_id).single()
