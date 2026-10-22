from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    request_id: str


def request_id_for(request: Request) -> str:
    return str(
        getattr(request.state, "request_id", None)
        or "unavailable"
    )


def error_response(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "request_id": request_id_for(request)},
    )


def install_error_handling(app: FastAPI) -> None:
    from app.model_gateway.base import ProviderFailure, ProviderTimeout
    from app.api.auth import AuthenticationFailed
    from app.auth.revocations import AuthenticationStorageError
    from app.courses.service import ResourceNotAvailable
    from app.diagnostics.repository import DiagnosticPersistenceError
    from app.diagnostics.service import ExecutionEvidenceUnavailable
    from app.memories.persistence import MemoryPersistenceError
    from app.memories.repository import IdempotencyConflict
    from app.memories.service import MemoryConflict, MemoryProposalNotEligible
    from app.submissions.repository import SubmissionPersistenceError

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(ProviderFailure)
    @app.exception_handler(ProviderTimeout)
    async def handle_model_failure(request: Request, exc: RuntimeError):
        code = "MODEL_PROVIDER_TIMEOUT" if isinstance(exc, ProviderTimeout) else "MODEL_PROVIDER_FAILURE"
        return error_response(request, 503, code, "Model provider request failed. Please retry.")

    @app.exception_handler(AuthenticationFailed)
    async def handle_authentication_failed(request: Request, _exc: AuthenticationFailed):
        return error_response(request, 401, "AUTHENTICATION_FAILED", "Authentication failed.")

    @app.exception_handler(ResourceNotAvailable)
    async def handle_resource_not_available(request: Request, _exc: ResourceNotAvailable):
        return error_response(request, 404, "RESOURCE_NOT_AVAILABLE", "Resource is not available.")

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, _exc: RequestValidationError):
        return error_response(request, 422, "VALIDATION_ERROR", "Request validation failed.")

    @app.exception_handler(ExecutionEvidenceUnavailable)
    async def handle_execution_unavailable(
        request: Request, _exc: ExecutionEvidenceUnavailable
    ):
        return error_response(
            request,
            409,
            "EXECUTION_EVIDENCE_UNAVAILABLE",
            "Execution evidence is unavailable.",
        )

    @app.exception_handler(DiagnosticPersistenceError)
    @app.exception_handler(SubmissionPersistenceError)
    @app.exception_handler(MemoryPersistenceError)
    @app.exception_handler(AuthenticationStorageError)
    async def handle_storage_unavailable(request: Request, _exc: RuntimeError):
        return error_response(
            request,
            503,
            "STORAGE_UNAVAILABLE",
            "The request could not be persisted safely.",
        )

    @app.exception_handler(IdempotencyConflict)
    @app.exception_handler(MemoryConflict)
    @app.exception_handler(MemoryProposalNotEligible)
    async def handle_memory_conflict(request: Request, exc: RuntimeError):
        return error_response(
            request,
            409,
            getattr(exc, "public_error_code", "MEMORY_STATE_CONFLICT"),
            getattr(
                exc,
                "public_message",
                "The memory state does not allow this operation.",
            ),
        )
