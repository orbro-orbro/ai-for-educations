from __future__ import annotations

import json
import os
import re
import socket
from typing import Any

from runner.worker.protocol import (
    CommandSummary,
    RunnerLimits,
    RunnerPhase,
    RunnerRequest,
    RunnerResult,
    RunnerStatus,
    ToolchainInfo,
)


class SandboxUnavailable(RuntimeError):
    pass


class DockerSandboxLauncher:
    """Launch exactly one fixed sandbox container for one validated request."""

    def __init__(self, client: Any = None, image: str | None = None) -> None:
        self._client = client
        self._image = image or os.environ.get(
            "RUNNER_SANDBOX_IMAGE", "knowbound-cj-runner-sandbox:1.2.0"
        )
        require_digest = os.environ.get("APP_ENV") == "production" or os.environ.get(
            "RUNNER_REQUIRE_IMAGE_DIGEST", "false"
        ).lower() in {"1", "true", "yes"}
        if require_digest and re.search(r"@sha256:[0-9a-fA-F]{64}$", self._image) is None:
            raise ValueError("production RUNNER_SANDBOX_IMAGE must use an immutable sha256 digest")

    def _docker_client(self):
        if self._client is not None:
            return self._client
        try:
            import docker
        except ModuleNotFoundError as exc:
            raise SandboxUnavailable("Docker SDK is unavailable") from exc
        try:
            self._client = docker.from_env()
            return self._client
        except Exception as exc:
            raise SandboxUnavailable("Docker Engine is unavailable") from exc

    def container_configuration(self) -> dict[str, Any]:
        return {
            "image": self._image,
            "entrypoint": ["python", "-m", "runner.worker.cli"],
            "command": [],
            "user": "10001:10001",
            "network_disabled": True,
            "network_mode": "none",
            "read_only": True,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "pids_limit": 64,
            "mem_limit": "512m",
            "nano_cpus": 1_000_000_000,
            "tmpfs": {"/work": "rw,nosuid,nodev,exec,size=64m,mode=0700,uid=10001,gid=10001"},
            "stdin_open": True,
            "tty": False,
            "auto_remove": False,
            "detach": True,
            "labels": {"knowbound.component": "cangjie-sandbox"},
        }

    def available(self) -> bool:
        try:
            return bool(self._docker_client().ping())
        except Exception:
            return False

    def execute(self, request: RunnerRequest) -> RunnerResult:
        container = None
        attached = None
        try:
            client = self._docker_client()
            container = client.containers.create(**self.container_configuration())
            container.start()
            attached = container.attach_socket(
                params={"stdin": 1, "stream": 1, "stdout": 0, "stderr": 0}
            )
            transport = getattr(attached, "_sock", attached)
            transport.sendall(request.model_dump_json().encode("utf-8"))
            transport.shutdown(socket.SHUT_WR)
            wait_result = container.wait(timeout=request.timeout_seconds + 15)
            output = container.logs(stdout=True, stderr=False)
            if isinstance(output, bytes):
                output = output.decode("utf-8", "replace")
            status_code = int(wait_result.get("StatusCode", 1))
            if status_code in {137, 152, 153} and not str(output).strip():
                return _control_result(
                    request,
                    RunnerStatus.resource_exhausted,
                    "sandbox terminated by a container resource limit",
                    status_code,
                )
            if status_code != 0 and not str(output).strip():
                raise SandboxUnavailable("sandbox worker exited without a result")
            return RunnerResult.model_validate(json.loads(str(output)))
        except SandboxUnavailable:
            raise
        except Exception as exc:
            if isinstance(exc, TimeoutError) or exc.__class__.__name__ in {"ReadTimeout", "Timeout"}:
                return _control_result(
                    request,
                    RunnerStatus.timed_out,
                    "sandbox exceeded the controller deadline",
                    None,
                )
            raise SandboxUnavailable("sandbox launch failed") from exc
        finally:
            if attached is not None:
                try:
                    attached.close()
                except Exception:
                    pass
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    pass


def _control_result(
    request: RunnerRequest,
    status: RunnerStatus,
    message: str,
    exit_code: int | None,
) -> RunnerResult:
    return RunnerResult(
        submission_id=request.submission_id,
        status=status,
        phase=RunnerPhase.control,
        retryable=False,
        exit_code=exit_code,
        signal=exit_code - 128 if exit_code is not None and exit_code >= 128 else None,
        stdout="",
        stderr=message,
        diagnostics=[],
        command_summary=CommandSummary(
            source_count=len(request.source_files), entrypoint=request.entrypoint
        ),
        limits=RunnerLimits(timeout_ms=request.timeout_ms),
        toolchain=ToolchainInfo(),
    )
