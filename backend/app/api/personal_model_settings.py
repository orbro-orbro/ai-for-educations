"""Per-user model configuration.

Every signed-in user sees the configuration that is actually used for their own
requests. A student may keep using the shared (teacher) configuration, or save a
personal provider that only affects their own diagnosis and hint calls. The
shared configuration is never writable from here; teachers keep using
``/teacher/model-settings``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Header, Request, Security
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import Authenticator
from app.api.contract import BEARER, errors
from app.api.errors import error_response
from app.auth.models import Actor, Role
from app.model_gateway.runtime import (
    ModelConfigurationError,
    ModelConfigurationLocked,
    ModelSettings,
    ModelSettingsService,
    ModelSettingsStorageError,
)

_ERROR_RESPONSES = errors(401, 409, 422, 503)

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


class PersonalModelSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: "own" saves the personal provider, "shared" drops it and inherits again.
    mode: Literal["own", "shared"] = "own"
    provider: _ProviderName | None = None
    model: Annotated[str, Field(max_length=128)] = ""
    base_url: Annotated[str, Field(max_length=512)] = ""
    api_key: Annotated[
        str,
        Field(max_length=512, json_schema_extra={"format": "password", "writeOnly": True}),
    ] = ""
    timeout_seconds: Annotated[float, Field(ge=1, le=120)] = 30.0


class SharedModelSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    configured: bool


class PersonalModelSettingsView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["shared", "own"]
    provider: str
    model: str
    base_url: str
    source: Literal["environment", "web"]
    configured: bool
    key_hint: str | None
    timeout_seconds: float
    personal_configured: bool
    shared: SharedModelSummary
    persistence: Literal["file", "memory"]
    environment_locked: bool


class PersonalModelProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: _ProbeStatus
    http_status: int | None


def _shared_configured(settings: ModelSettings) -> bool:
    return bool(settings.api_key) if settings.is_remote else True


def _view(service: ModelSettingsService, actor: Actor) -> PersonalModelSettingsView:
    shared = service.snapshot()
    personal = (
        service.personal_settings(actor.user_id) if actor.role is Role.STUDENT else None
    )
    effective = personal if personal is not None else shared
    scope: Literal["shared", "own"] = "own" if personal is not None else "shared"
    return PersonalModelSettingsView(
        scope=scope,
        provider=effective.provider,
        model=effective.model,
        base_url=effective.base_url,
        source="environment" if effective.source == "environment" else "web",
        configured=_shared_configured(effective),
        # The teacher's key hint belongs to the teacher; a student inheriting the
        # shared configuration only learns whether a key exists.
        key_hint=effective.key_hint if scope == "own" else None,
        timeout_seconds=effective.timeout_seconds,
        personal_configured=personal is not None,
        shared=SharedModelSummary(
            provider=shared.provider,
            model=shared.model,
            configured=_shared_configured(shared),
        ),
        persistence=service.persistence,
        environment_locked=service.environment_locked,
    )


def _locked_error(request: Request):
    return error_response(
        request,
        409,
        "MODEL_CONFIGURATION_MANAGED",
        "Model configuration is managed by the deployment environment.",
    )


def create_personal_model_settings_router(
    service: ModelSettingsService, authenticator: Authenticator
) -> APIRouter:
    router = APIRouter(tags=["model"], dependencies=[Security(BEARER)])

    @router.get(
        "/model-settings",
        response_model=PersonalModelSettingsView,
        operation_id="getMyModelSettings",
        responses=_ERROR_RESPONSES,
    )
    def read_my_model_settings(
        request: Request,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        actor = authenticator.authenticate_header(authorization)
        return _view(service, actor)

    @router.put(
        "/model-settings",
        response_model=PersonalModelSettingsView,
        operation_id="updateMyModelSettings",
        responses=_ERROR_RESPONSES,
    )
    def update_my_model_settings(
        request: Request,
        payload: PersonalModelSettingsUpdate,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        actor = authenticator.authenticate_header(authorization)
        if actor.role is not Role.STUDENT:
            return error_response(
                request,
                422,
                "VALIDATION_ERROR",
                "Teachers change the shared configuration from the teacher panel.",
            )
        try:
            if payload.mode == "shared":
                service.clear_personal(actor.user_id)
            else:
                if payload.provider is None:
                    return error_response(
                        request,
                        422,
                        "VALIDATION_ERROR",
                        "provider must be configured",
                    )
                service.apply_personal(
                    actor.user_id, payload.model_dump(exclude={"mode"})
                )
        except ModelConfigurationLocked:
            return _locked_error(request)
        except ModelConfigurationError as exc:
            return error_response(request, 422, "VALIDATION_ERROR", str(exc))
        except ModelSettingsStorageError:
            return error_response(
                request,
                503,
                "STORAGE_UNAVAILABLE",
                "Model configuration could not be stored.",
            )
        return _view(service, actor)

    @router.post(
        "/model-settings/probe",
        response_model=PersonalModelProbeResult,
        operation_id="probeMyModelSettings",
        responses=_ERROR_RESPONSES,
    )
    def probe_my_model_settings(
        request: Request,
        payload: PersonalModelSettingsUpdate,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        actor = authenticator.authenticate_header(authorization)
        data = payload.model_dump(exclude={"mode"})
        if not data.get("provider"):
            return error_response(
                request, 422, "VALIDATION_ERROR", "provider must be configured"
            )
        try:
            if actor.role is Role.STUDENT:
                outcome = service.probe_personal(actor.user_id, data)
            else:
                outcome = service.probe(data)
        except ModelConfigurationLocked:
            return _locked_error(request)
        except ModelConfigurationError as exc:
            return error_response(request, 422, "VALIDATION_ERROR", str(exc))
        except RuntimeError:
            return error_response(
                request, 422, "VALIDATION_ERROR", "the environment configuration is incomplete"
            )
        return PersonalModelProbeResult(
            status=outcome.status, http_status=outcome.http_status
        )

    return router


__all__ = [
    "PersonalModelProbeResult",
    "PersonalModelSettingsUpdate",
    "PersonalModelSettingsView",
    "SharedModelSummary",
    "create_personal_model_settings_router",
]
