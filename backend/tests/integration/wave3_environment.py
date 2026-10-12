"""Trusted initializer for dedicated synthetic Wave 3 databases only."""
import json
import subprocess

DATABASES = ("wave3_task6", "wave3_task7", "wave3_task10", "wave3_router", "wave3_migration", "wave3_browser")
PROJECT = "knowbound-wave3-gate"
CONTAINER = PROJECT + "-postgres-1"


def validate_target(labels: dict[str, str], database: str) -> None:
    if labels.get("com.docker.compose.project") != PROJECT or labels.get("knowbound.task") != "wave3-integration-gate":
        raise ValueError("Resource is not labeled for this Gate")
    if database not in DATABASES:
        raise ValueError("Database is not an approved synthetic Gate database")


def initialize() -> None:
    result = subprocess.run(["docker", "inspect", CONTAINER, "--format", "{{json .Config.Labels}}"], check=True, capture_output=True, text=True)
    labels = json.loads(result.stdout)
    for database in DATABASES:
        validate_target(labels, database)
        existing = subprocess.run(["docker", "exec", CONTAINER, "psql", "-U", "knowbound", "-d", "knowbound", "-Atc", f"SELECT 1 FROM pg_database WHERE datname='{database}'"], check=True, capture_output=True, text=True)
        if not existing.stdout.strip():
            subprocess.run(["docker", "exec", CONTAINER, "createdb", "-U", "knowbound", database], check=True)
        subprocess.run(["docker", "exec", CONTAINER, "psql", "-U", "knowbound", "-d", database, "-c", "CREATE EXTENSION IF NOT EXISTS vector"], check=True, capture_output=True)
    print("Initialized six isolated synthetic databases with vector extension")


if __name__ == "__main__":
    initialize()
