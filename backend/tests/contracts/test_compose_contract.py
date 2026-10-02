from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


def _environment_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_compose_has_buildable_api_web_controller_and_sandbox_topology():
    document = yaml.safe_load((ROOT / "infra/compose/docker-compose.yml").read_text(encoding="utf-8"))
    services = document["services"]
    assert {"postgres", "api", "web", "runner-controller", "runner-sandbox"} <= set(services)
    assert "runner-controller:8080" in services["api"]["environment"]["RUNNER_ENDPOINT"]
    assert services["runner-controller"]["networks"] == ["internal"]
    assert services["runner-sandbox"]["network_mode"] == "none"
    assert services["runner-sandbox"]["read_only"] is True
    assert services["runner-sandbox"]["user"] == "10001:10001"
    assert services["runner-sandbox"]["cap_drop"] == ["ALL"]
    assert services["runner-sandbox"]["pids_limit"] == 64
    assert "profiles" not in services["runner-sandbox"]
    assert services["runner-controller"]["depends_on"]["runner-sandbox"]["condition"] == "service_completed_successfully"


def test_referenced_build_files_exist():
    assert (ROOT / "backend/Dockerfile").is_file()
    assert (ROOT / "frontend/Dockerfile").is_file()
    assert (ROOT / "runner/controller.Dockerfile").is_file()
    assert (ROOT / "runner/Dockerfile").is_file()


def test_environment_example_matches_wave1_compose_contract():
    environment = _environment_example()

    assert environment["APP_ENV"] == "development"
    assert environment["DATABASE_URL"] == (
        "postgresql+psycopg://knowbound:change-me@postgres:5432/knowbound"
    )
    assert environment["RUNNER_ENDPOINT"] == "http://runner-controller:8080"
    assert environment["AUTH_TOKEN_SECRET"] == "development-only-token-secret"
    assert environment["BOOTSTRAP_TEACHER_USERNAME"] == "teacher"
    assert environment["BOOTSTRAP_TEACHER_PASSWORD"] == "teacher-change-me"
    assert environment["BOOTSTRAP_STUDENT_USERNAME"] == "student"
    assert environment["BOOTSTRAP_STUDENT_PASSWORD"] == "student-change-me"
    assert environment["RUNNER_SANDBOX_IMAGE"] == "knowbound-cj-runner-sandbox:1.2.0"
    assert environment["DOCKER_GID"] == "0"


def test_docker_build_contexts_exclude_local_artifacts():
    required_patterns = {
        "backend": {".pytest_cache/", "__pycache__/", ".venv/", "*.db", "*.sqlite*"},
        "frontend": {"node_modules/", "dist/"},
        "runner": {".pytest_cache/", "__pycache__/"},
    }

    for context, expected in required_patterns.items():
        ignore_file = ROOT / context / ".dockerignore"
        assert ignore_file.is_file(), context
        patterns = {
            line.strip()
            for line in ignore_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        assert expected <= patterns, context


def test_api_receives_course_seed_as_read_only_data():
    document = yaml.safe_load((ROOT / "infra/compose/docker-compose.yml").read_text(encoding="utf-8"))

    assert "../../data/course_seed:/data/course_seed:ro" in document["services"]["api"]["volumes"]
    assert (ROOT / "data/course_seed/cangjie_concepts.yaml").is_file()
    assert (ROOT / "data/course_seed/cangjie_misconceptions.yaml").is_file()
