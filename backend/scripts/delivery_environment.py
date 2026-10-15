"""Trusted initializer restricted to this task's labeled synthetic PostgreSQL."""
import json
import subprocess

DATABASES = tuple("wave4_" + name for name in ("task6", "task7", "task10", "router", "migration", "browser"))
PROJECT = "knowbound-wave4-test"
CONTAINER = PROJECT + "-postgres-1"


def validate_target(labels: dict[str, str], database: str) -> None:
    if labels.get("com.docker.compose.project") != PROJECT or labels.get("knowbound.task") != "wave4-task11-test":
        raise ValueError("Resource is not labeled for Task 11 regression")
    if database not in DATABASES:
        raise ValueError("Not an approved Task 11 synthetic database")


def initialize() -> None:
    result = subprocess.run(["docker", "inspect", CONTAINER, "--format", "{{json .Config.Labels}}"], check=True, capture_output=True, text=True)
    labels = json.loads(result.stdout)
    for database in DATABASES:
        validate_target(labels, database)
        existing = subprocess.run(["docker", "exec", CONTAINER, "psql", "-U", "knowbound", "-d", "knowbound", "-Atc", f"SELECT 1 FROM pg_database WHERE datname='{database}'"], check=True, capture_output=True, text=True)
        if not existing.stdout.strip():
            subprocess.run(["docker", "exec", CONTAINER, "createdb", "-U", "knowbound", database], check=True)
        subprocess.run(["docker", "exec", CONTAINER, "psql", "-U", "knowbound", "-d", database, "-c", "CREATE EXTENSION IF NOT EXISTS vector"], check=True, capture_output=True)
    print("Initialized six Task 11 synthetic databases with vector extension")


if __name__ == "__main__":
    initialize()
