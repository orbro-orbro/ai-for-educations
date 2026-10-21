from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Header, Request, Security
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import Authenticator
from app.api.contract import BEARER, errors
from app.api.errors import error_response
from app.auth.models import Actor, Role
from app.courses.service import ResourceNotAvailable
from app.model_gateway.runtime import (
    ModelConfigurationError,
    ModelConfigurationLocked,
    ModelSettingsService,
    ModelSettingsStorageError,
)

_ERROR_RESPONSES = errors(401, 404, 409, 422, 503)

_ProviderName = Literal[
    "environment", "deepseek", "qwen", "openai_compatible", "mock", "disabled"
]
_ProbeStatus = Literal[
    "ok",
    "invalid_credentials",
    "model_or_endpoint_not_found",
    "rate_limited",
    "rejected_request",
    "timeout",
    "transport_error",
    "http_error",
]


class ModelSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: _ProviderName
    model: Annotated[str, Field(max_length=128)] = ""
    base_url: Annotated[str, Field(max_length=512)] = ""
    api_key: Annotated[
        str,
        Field(max_length=512, json_schema_extra={"format": "password", "writeOnly": True}),
    ] = ""
    timeout_seconds: Annotated[float, Field(ge=1, le=120)] = 30.0


class ModelSettingsView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    base_url: str
    source: Literal["environment", "web"]
    configured: bool
    key_hint: str | None
    timeout_seconds: float
    persistence: Literal["file", "memory"]
    environment_locked: bool


class ModelProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: _ProbeStatus
    http_status: int | None


def _view(service: ModelSettingsService) -> ModelSettingsView:
    settings = service.snapshot()
    return ModelSettingsView(
        provider=settings.provider,
        model=settings.model,
        base_url=settings.base_url,
        source="environment" if settings.source == "environment" else "web",
        configured=bool(settings.api_key) if settings.is_remote else True,
        key_hint=settings.key_hint,
        timeout_seconds=settings.timeout_seconds,
        persistence=service.persistence,
        environment_locked=service.environment_locked,
    )


def _teacher(authenticator: Authenticator, authorization: str | None) -> Actor:
    actor = authenticator.authenticate_header(authorization)
    if actor.role is not Role.TEACHER:
        # Teacher-only settings must not disclose their existence to students.
        raise ResourceNotAvailable()
    return actor


def _configuration_error(request: Request, message: str):
    return error_response(request, 422, "VALIDATION_ERROR", message)


def _locked_error(request: Request):
    return error_response(
        request,
        409,
        "MODEL_CONFIGURATION_MANAGED",
        "Model configuration is managed by the deployment environment.",
    )


def create_model_settings_router(
    service: ModelSettingsService, authenticator: Authenticator
) -> APIRouter:
    router = APIRouter(tags=["teacher"], dependencies=[Security(BEARER)])

    @router.get(
        "/teacher/model-settings",
        response_model=ModelSettingsView,
        operation_id="getTeacherModelSettings",
        responses=_ERROR_RESPONSES,
    )
    def read_model_settings(
        request: Request,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        _teacher(authenticator, authorization)
        return _view(service)

    @router.put(
        "/teacher/model-settings",
        response_model=ModelSettingsView,
        operation_id="updateTeacherModelSettings",
        responses=_ERROR_RESPONSES,
    )
    def update_model_settings(
        request: Request,
        payload: ModelSettingsUpdate,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        _teacher(authenticator, authorization)
        try:
            if payload.provider == "environment":
                service.restore_environment()
            else:
                service.apply(payload.model_dump())
        except ModelConfigurationLocked:
            return _locked_error(request)
        except ModelConfigurationError as exc:
            return _configuration_error(request, str(exc))
        except RuntimeError:
            return _configuration_error(
                request, "the environment configuration is incomplete"
            )
        except ModelSettingsStorageError:
            return error_response(
                request,
                503,
                "STORAGE_UNAVAILABLE",
                "Model configuration could not be stored.",
            )
        return _view(service)

    @router.post(
        "/teacher/model-settings/probe",
        response_model=ModelProbeResult,
        operation_id="probeTeacherModelSettings",
        responses=_ERROR_RESPONSES,
    )
    def probe_model_settings(
        request: Request,
        payload: ModelSettingsUpdate,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        _teacher(authenticator, authorization)
        try:
            outcome = service.probe(payload.model_dump())
        except ModelConfigurationLocked:
            return _locked_error(request)
        except ModelConfigurationError as exc:
            return _configuration_error(request, str(exc))
        return ModelProbeResult(status=outcome.status, http_status=outcome.http_status)

    return router


__all__ = [
    "ModelProbeResult",
    "ModelSettingsUpdate",
    "ModelSettingsView",
    "create_model_settings_router",
]
