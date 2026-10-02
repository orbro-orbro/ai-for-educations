from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


def _example_environment() -> dict[str, str]:
    values = {}
    for raw_line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


def test_example_environment_matches_compose_and_readme_contract():
    environment = _example_environment()
    compose = yaml.safe_load(
        (ROOT / "infra/compose/docker-compose.yml").read_text(encoding="utf-8")
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required = {
        "AUTH_TOKEN_SECRET",
        "BOOTSTRAP_TEACHER_USERNAME",
        "BOOTSTRAP_TEACHER_PASSWORD",
        "BOOTSTRAP_STUDENT_USERNAME",
        "BOOTSTRAP_STUDENT_PASSWORD",
        "RUNNER_ENDPOINT",
        "RUNNER_SANDBOX_IMAGE",
        "DOCKER_GID",
    }

    assert required <= environment.keys()
    assert environment["RUNNER_ENDPOINT"] == "http://runner-controller:8080"
    assert (
        environment["DATABASE_URL"]
        == "postgresql+psycopg://knowbound:change-me@postgres:5432/knowbound"
    )
    assert all(
        key in compose["services"]["api"]["environment"]
        for key in required - {"RUNNER_SANDBOX_IMAGE", "DOCKER_GID"}
    )
    assert all(
        key in compose["services"]["runner-controller"]["environment"]
        or key == "DOCKER_GID"
        for key in {"RUNNER_SANDBOX_IMAGE", "DOCKER_GID"}
    )
    assert any(
        "DOCKER_GID" in value
        for value in compose["services"]["runner-controller"]["group_add"]
    )
    assert all(key in readme for key in required)
    assert "仅用于本地开发" in (ROOT / ".env.example").read_text(encoding="utf-8")


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


def test_api_image_contains_course_seed_where_bootstrap_loads_it():
    from pathlib import PurePosixPath

    compose = yaml.safe_load(
        (ROOT / "infra/compose/docker-compose.yml").read_text(encoding="utf-8")
    )
    build = compose["services"]["api"]["build"]
    seed_contexts = {
        name: path
        for name, path in build.get("additional_contexts", {}).items()
        if (ROOT / "infra/compose" / path).resolve() == (ROOT / "data/course_seed").resolve()
    }
    dockerfile = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    in_image_seed_dir = (
        PurePosixPath("/app/app/knowledge/seed.py").parents[3] / "data/course_seed"
    )

    assert len(seed_contexts) == 1
    (context_name,) = seed_contexts
    assert f"COPY --from={context_name} . {in_image_seed_dir}" in dockerfile


def test_referenced_build_files_exist():
    assert (ROOT / "backend/Dockerfile").is_file()
    assert (ROOT / "frontend/Dockerfile").is_file()
    assert (ROOT / "runner/controller.Dockerfile").is_file()
    assert (ROOT / "runner/Dockerfile").is_file()
