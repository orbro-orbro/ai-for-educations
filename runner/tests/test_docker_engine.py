import socket

import pytest

from runner.controller.docker_engine import DockerSandboxLauncher
from runner.worker.protocol import (
    CommandSummary,
    RunnerLimits,
    RunnerPhase,
    RunnerRequest,
    RunnerResult,
    RunnerStatus,
    ToolchainInfo,
)


def test_container_configuration_pins_every_isolation_boundary():
    launcher = DockerSandboxLauncher(client=object(), image="knowbound-cj-runner-sandbox@sha256:abc")

    config = launcher.container_configuration()

    assert config["image"] == "knowbound-cj-runner-sandbox@sha256:abc"
    assert config["entrypoint"] == ["python", "-m", "runner.worker.cli"]
    assert config["command"] == []
    assert config["user"] == "10001:10001"
    assert config["network_disabled"] is True
    assert config["network_mode"] == "none"
    assert config["read_only"] is True
    assert config["cap_drop"] == ["ALL"]
    assert config["security_opt"] == ["no-new-privileges:true"]
    assert config["pids_limit"] == 64
    assert config["mem_limit"] == "512m"
    assert config["nano_cpus"] == 1_000_000_000
    assert set(config["tmpfs"]) == {"/work"}
    assert "volumes" not in config
    assert "ports" not in config
    assert config["stdin_open"] is True
    assert config["auto_remove"] is False


def test_container_configuration_only_uses_arguments_the_docker_sdk_accepts():
    containers = pytest.importorskip("docker.models.containers")
    config = DockerSandboxLauncher(client=object(), image="fixed@sha256:one").container_configuration()

    accepted = {"image", "command", *containers.RUN_CREATE_KWARGS, *containers.RUN_HOST_CONFIG_KWARGS}
    assert set(config) <= accepted


def test_sandbox_image_is_not_derived_from_request_data():
    first = DockerSandboxLauncher(client=object(), image="fixed@sha256:one").container_configuration()
    second = DockerSandboxLauncher(client=object(), image="fixed@sha256:one").container_configuration()
    assert first == second


def test_production_requires_an_immutable_sandbox_image_digest(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ValueError, match="digest"):
        DockerSandboxLauncher(client=object(), image="knowbound-cj-runner-sandbox:1.2.0")
    launcher = DockerSandboxLauncher(
        client=object(), image="knowbound-cj-runner-sandbox@sha256:" + ("a" * 64)
    )
    assert "@sha256:" in launcher.container_configuration()["image"]


def test_launcher_streams_validated_json_and_always_closes_and_removes_container():
    result = RunnerResult(
        submission_id="sub-1",
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

    class Transport:
        payload = b""
        shutdown_mode = None

        def sendall(self, value):
            self.payload += value

        def shutdown(self, mode):
            self.shutdown_mode = mode

    class Attached:
        def __init__(self):
            self._sock = Transport()
            self.closed = False

        def close(self):
            self.closed = True

    class Container:
        def __init__(self):
            self.attached = Attached()
            self.removed = False

        def start(self):
            pass

        def attach_socket(self, params):
            return self.attached

        def wait(self, timeout):
            return {"StatusCode": 0}

        def logs(self, **kwargs):
            return result.model_dump_json().encode()

        def remove(self, force):
            assert force is True
            self.removed = True

    container = Container()

    class Containers:
        def create(self, **kwargs):
            return container

    class Client:
        containers = Containers()

    request = RunnerRequest(
        submission_id="sub-1",
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        timeout_ms=1_000,
    )
    observed = DockerSandboxLauncher(client=Client(), image="fixed").execute(request)

    assert observed == result
    assert RunnerRequest.model_validate_json(container.attached._sock.payload) == request
    assert container.attached._sock.payload.endswith(b"\n")
    assert container.attached._sock.payload.count(b"\n") == 1
    assert container.attached._sock.shutdown_mode == socket.SHUT_WR
    assert container.attached.closed is True
    assert container.removed is True


def test_container_level_resource_kill_is_not_misreported_as_runner_unavailable():
    class Transport:
        def sendall(self, value):
            pass

        def shutdown(self, mode):
            pass

    class Attached:
        _sock = Transport()

        def close(self):
            pass

    class Container:
        def start(self):
            pass

        def attach_socket(self, params):
            return Attached()

        def wait(self, timeout):
            return {"StatusCode": 137}

        def logs(self, **kwargs):
            return b""

        def remove(self, force):
            pass

    class Client:
        class Containers:
            def create(self, **kwargs):
                return Container()

        containers = Containers()

    request = RunnerRequest(
        submission_id="sub-resource",
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        timeout_ms=1_000,
    )
    result = DockerSandboxLauncher(client=Client(), image="fixed").execute(request)

    assert result.status is RunnerStatus.resource_exhausted
    assert result.phase is RunnerPhase.control
    assert result.retryable is False
    assert result.exit_code == 137


class ReadTimeoutError(Exception):
    pass


class ConnectionError(OSError):
    pass


@pytest.mark.parametrize(
    "wait_error",
    [
        TimeoutError("wait exceeded"),
        # docker SDK over the Unix socket wraps urllib3's read timeout in requests' ConnectionError.
        ConnectionError(ReadTimeoutError("UnixHTTPConnectionPool(host='localhost', port=None): Read timed out.")),
    ],
)
def test_controller_wait_timeout_remains_a_non_retryable_execution_timeout(wait_error):
    class Transport:
        def sendall(self, value):
            pass

        def shutdown(self, mode):
            pass

    class Attached:
        _sock = Transport()

        def close(self):
            pass

    class Container:
        removed = False

        def start(self):
            pass

        def attach_socket(self, params):
            return Attached()

        def wait(self, timeout):
            raise wait_error

        def remove(self, force):
            self.removed = True

    container = Container()

    class Client:
        class Containers:
            def create(self, **kwargs):
                return container

        containers = Containers()

    request = RunnerRequest(
        submission_id="sub-timeout",
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        timeout_ms=1_000,
    )
    result = DockerSandboxLauncher(client=Client(), image="fixed").execute(request)

    assert result.status is RunnerStatus.timed_out
    assert result.phase is RunnerPhase.control
    assert result.retryable is False
    assert container.removed is True
