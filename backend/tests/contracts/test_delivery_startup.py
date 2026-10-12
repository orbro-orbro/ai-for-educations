from pathlib import Path
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = yaml.safe_load((ROOT / "infra/compose/docker-compose.yml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("service", ["api", "web", "postgres", "runner-controller"])
def test_long_lived_services_report_health(service):
    check = COMPOSE["services"][service]["healthcheck"]
    assert check["test"] and check["retries"] > 0


def test_web_waits_for_healthy_api_and_runner_timeout_is_forwarded():
    services = COMPOSE["services"]
    assert services["web"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert services["api"]["environment"]["RUNNER_TIMEOUT_SECONDS"] == "${RUNNER_TIMEOUT_SECONDS:-15}"


@pytest.mark.parametrize("service", ["api", "web"])
def test_publication_is_loopback_only(service):
    assert all(port.startswith("127.0.0.1:") for port in COMPOSE["services"][service]["ports"])


@pytest.mark.parametrize("dockerfile", ["backend/Dockerfile", "runner/Dockerfile", "runner/controller.Dockerfile"])
def test_python_images_install_exact_locked_requirements_without_resolution(dockerfile):
    source = (ROOT / dockerfile).read_text(encoding="utf-8")
    assert "--require-hashes" in source
    assert "--no-deps" in source
    assert ".lock" in source


def test_frontend_and_database_images_are_digest_pinned():
    assert "@sha256:" in (ROOT / "frontend/Dockerfile").read_text(encoding="utf-8").splitlines()[0]
    assert "@sha256:" in COMPOSE["services"]["postgres"]["image"]
