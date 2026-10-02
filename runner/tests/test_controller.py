from __future__ import annotations

import anyio
import yaml
from httpx import ASGITransport, AsyncClient
from pathlib import Path

from runner.controller.app import SandboxUnavailable, create_app
from runner.worker.protocol import (
    CommandSummary,
    RunnerLimits,
    RunnerPhase,
    RunnerResult,
    RunnerStatus,
    ToolchainInfo,
)


REQUEST = {
    "protocol_version": "2",
    "submission_id": "sub-controller",
    "source_files": [{"path": "main.cj", "content": "main() {}"}],
    "entrypoint": "main.cj",
    "timeout_ms": 1_000,
}
ROOT = Path(__file__).resolve().parents[2]


def _result() -> RunnerResult:
    return RunnerResult(
        submission_id="sub-controller",
        status=RunnerStatus.succeeded,
        phase=RunnerPhase.run,
        retryable=False,
        exit_code=0,
        signal=None,
        stdout="ok",
        stderr="",
        diagnostics=[],
        command_summary=CommandSummary(source_count=1, entrypoint="main.cj"),
        limits=RunnerLimits(timeout_ms=1_000),
        toolchain=ToolchainInfo(),
    )


def _post(app, body):
    async def go():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/v2/execute", json=body)

    return anyio.run(go)


def test_controller_returns_worker_result_from_injected_launcher():
    class Launcher:
        def execute(self, request):
            assert request.submission_id == "sub-controller"
            return _result()

        def available(self):
            return True

    response = _post(create_app(Launcher()), REQUEST)
    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"


def test_controller_maps_engine_unavailability_to_retryable_result():
    class Launcher:
        def execute(self, request):
            raise SandboxUnavailable("docker engine unavailable")

        def available(self):
            return False

    response = _post(create_app(Launcher()), REQUEST)
    assert response.status_code == 503
    assert response.json()["status"] == "runner_unavailable"
    assert response.json()["retryable"] is True


def test_controller_rejects_attempt_to_override_image_command_or_network():
    class Launcher:
        def execute(self, request):
            raise AssertionError("launcher must not run")

        def available(self):
            return True

    body = REQUEST | {"image": "attacker/image", "command": ["sh"], "network_mode": "host"}
    response = _post(create_app(Launcher()), body)
    assert response.status_code == 422


def test_controller_openapi_documents_retryable_unavailable_result():
    class Launcher:
        def execute(self, request):
            return _result()

        def available(self):
            return True

    contract = create_app(Launcher()).openapi()
    execute_responses = contract["paths"]["/v2/execute"]["post"]["responses"]
    assert execute_responses["200"]["content"]["application/json"]["schema"]["$ref"].endswith("RunnerResult")
    assert execute_responses["503"]["content"]["application/json"]["schema"]["$ref"].endswith("RunnerResult")


def test_checked_in_runner_contract_matches_runtime_schema():
    checked_in = yaml.safe_load((ROOT / "contracts/runner-openapi.yaml").read_text(encoding="utf-8"))
    assert checked_in == create_app().openapi()

