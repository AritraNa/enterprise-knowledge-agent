from .constraints import UNIQUE_CONSTRAINTS
from .indexes import INDEXES


class SchemaManager:

    def __init__(self, driver):
        self.driver = driver

    def initialize(self):
        with self.driver.session() as session:
            self._create_constraints(session)
            self._create_indexes(session)

    def _create_constraints(self, session):
        for label, property_name in UNIQUE_CONSTRAINTS.items():
            constraint_name = f"{label.lower()}_{property_name}_unique"

            query = f"""
            CREATE CONSTRAINT {constraint_name} IF NOT EXISTS
            FOR (n:{label})
            REQUIRE n.{property_name} IS UNIQUE
            """

            session.run(query)

    def _create_indexes(self, session):
        for label, properties in INDEXES.items():
            for property_name in properties:
                index_name = f"{label.lower()}_{property_name}_idx"

                query = f"""
                CREATE INDEX {index_name} IF NOT EXISTS
                FOR (n:{label})
                ON (n.{property_name})
                """

                session.run(query)
