import os
from neo4j import GraphDatabase

from .schema.manager import SchemaManager


class Neo4jStore:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(
                os.environ["NEO4J_USERNAME"],
                os.environ["NEO4J_PASSWORD"],
            ),
        )

    def close(self):
        self.driver.close()

    def verify(self):
        self.driver.verify_connectivity()

    def init_schema(self):
        schema_manager = SchemaManager(self.driver)
        schema_manager.initialize()
