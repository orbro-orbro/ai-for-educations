from __future__ import annotations

from typing import Protocol

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from runner.controller.docker_engine import DockerSandboxLauncher, SandboxUnavailable
from runner.worker.protocol import RunnerRequest, RunnerResult


class SandboxLauncher(Protocol):
    def available(self) -> bool: ...
    def execute(self, request: RunnerRequest) -> RunnerResult: ...


def create_app(launcher: SandboxLauncher | None = None) -> FastAPI:
    application = FastAPI(title="KnowBound-CJ Runner Controller", version="2")
    application.state.launcher = launcher or DockerSandboxLauncher()

    @application.get("/health")
    async def health():
        available = await run_in_threadpool(application.state.launcher.available)
        return JSONResponse(
            status_code=200 if available else 503,
            content={"status": "ok" if available else "unavailable"},
        )

    @application.post(
        "/v2/execute",
        response_model=RunnerResult,
        responses={503: {"model": RunnerResult, "description": "Sandbox infrastructure is unavailable; retryable is true."}},
    )
    async def execute(request: RunnerRequest):
        try:
            result = await run_in_threadpool(application.state.launcher.execute, request)
        except SandboxUnavailable as exc:
            result = RunnerResult.unavailable(request.submission_id, str(exc))
            return JSONResponse(status_code=503, content=result.model_dump(mode="json"))
        return result

    return application


app = create_app()
