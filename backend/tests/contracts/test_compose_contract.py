from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


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
