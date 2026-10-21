"""Runtime model configuration: swap the provider without restarting the API.

Two layers share one file: the shared (teacher) configuration every request
falls back to, and one optional personal override per user. The services keep a
single ``UserScopedModelProvider`` for their whole lifetime; it resolves the
effective provider per request, so a new key or model takes effect immediately.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

import httpx

from app.model_gateway.base import (
    DiagnosisModelOutput,
    DiagnosisRequest,
    ExplanationCheckRequest,
    ExplanationModelOutput,
    HintModelOutput,
    HintRequest,
    ModelProvider,
)
from app.model_gateway.config import (
    CHAT_PROVIDER_PRESETS,
    DisabledModelProvider,
    model_provider_from_config,
)
from app.model_gateway.mock import DeterministicMockProvider
from app.model_gateway.openai_chat_completions import OpenAIChatCompletionsProvider


_LOG = logging.getLogger(__name__)

REMOTE_PROVIDERS = ("deepseek", "qwen", "openai_compatible")
CONTROL_PROVIDERS = ("environment", "mock", "disabled")
SUPPORTED_PROVIDERS = REMOTE_PROVIDERS + CONTROL_PROVIDERS

PROBE_STATUSES = (
    "ok",
    "invalid_credentials",
    "model_or_endpoint_not_found",
    "rate_limited",
    "rejected_request",
    "timeout",
    "transport_error",
    "http_error",
)

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class ModelConfigurationError(ValueError):
    """A rejected configuration. The message is safe to show to the operator."""


class ModelConfigurationLocked(RuntimeError):
    """The deployment manages model configuration through the environment."""


class ModelSettingsStorageError(RuntimeError):
    """The runtime configuration could not be read or written."""


@dataclass(frozen=True, repr=False)
class ModelSettings:
    provider: str
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    timeout_seconds: float = 30.0
    source: str = "web"

    def __repr__(self) -> str:
        """Never let a dataclass repr leak the key into logs or tracebacks."""
        return (
            f"ModelSettings(provider={self.provider!r}, model={self.model!r}, "
            f"base_url={self.base_url!r}, api_key={self.key_hint!r}, "
            f"timeout_seconds={self.timeout_seconds!r}, source={self.source!r})"
        )

    @property
    def is_remote(self) -> bool:
        return self.provider in REMOTE_PROVIDERS

    @property
    def key_hint(self) -> str | None:
        if not self.api_key:
            return None
        if len(self.api_key) <= 4:
            return "*" * len(self.api_key)
        return "*" * 4 + self.api_key[-4:]

    def stored_payload(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class ProbeOutcome:
    status: str
    http_status: int | None = None


def _timeout_seconds(value: Any) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ModelConfigurationError("timeout_seconds must be a number") from exc
    if not 1 <= timeout <= 120:
        raise ModelConfigurationError("timeout_seconds must be between 1 and 120")
    return timeout


def _validate_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ModelConfigurationError("base_url must be an absolute http(s) URL")
    if parsed.scheme == "http" and parsed.hostname not in _LOOPBACK_HOSTS:
        raise ModelConfigurationError("base_url must use https")
    if parsed.username or parsed.password:
        raise ModelConfigurationError("base_url must not embed credentials")


def validated_settings(payload: Mapping[str, Any], *, source: str = "web") -> ModelSettings:
    """Validate one configuration request. Secrets are never echoed in errors."""
    provider = str(payload.get("provider") or "").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ModelConfigurationError("unsupported provider")
    timeout_seconds = _timeout_seconds(payload.get("timeout_seconds", 30.0))
    if provider not in REMOTE_PROVIDERS:
        return ModelSettings(
            provider=provider, timeout_seconds=timeout_seconds, source=source
        )
    model = str(payload.get("model") or "").strip()
    if not model:
        raise ModelConfigurationError("model must be configured for the selected provider")
    if len(model) > 128:
        raise ModelConfigurationError("model is too long")
    api_key = str(payload.get("api_key") or "").strip()
    if not api_key:
        raise ModelConfigurationError("api_key must be configured for the selected provider")
    base_url = str(payload.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        preset = CHAT_PROVIDER_PRESETS.get(provider)
        if preset is None:
            raise ModelConfigurationError("base_url must be configured for this provider")
        base_url = preset[1]
    _validate_base_url(base_url)
    return ModelSettings(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        source=source,
    )


def settings_from_environment(environ: Mapping[str, str] | None = None) -> ModelSettings:
    """Describe the configuration the deployment started with."""
    values = os.environ if environ is None else environ
    provider = values.get("MODEL_PROVIDER", "").strip().lower()
    try:
        timeout_seconds = _timeout_seconds(values.get("MODEL_TIMEOUT_SECONDS", "30"))
    except ModelConfigurationError:
        timeout_seconds = 30.0
    if provider in {"", "disabled"}:
        return ModelSettings(provider="disabled", timeout_seconds=timeout_seconds, source="environment")
    if provider == "mock":
        return ModelSettings(provider="mock", timeout_seconds=timeout_seconds, source="environment")
    if provider in CHAT_PROVIDER_PRESETS:
        key_variable, default_base = CHAT_PROVIDER_PRESETS[provider]
        return ModelSettings(
            provider=provider,
            model=values.get("MODEL_NAME", "").strip(),
            base_url=(values.get("MODEL_BASE_URL", "").strip() or default_base).rstrip("/"),
            api_key=values.get(key_variable, "").strip(),
            timeout_seconds=timeout_seconds,
            source="environment",
        )
    if provider == "openai":
        return ModelSettings(
            provider="openai_compatible",
            model=values.get("MODEL_NAME", "").strip(),
            base_url=(values.get("OPENAI_BASE_URL", "").strip() or "https://api.openai.com").rstrip("/"),
            api_key=values.get("OPENAI_API_KEY", "").strip(),
            timeout_seconds=timeout_seconds,
            source="environment",
        )
    return ModelSettings(provider=provider, timeout_seconds=timeout_seconds, source="environment")


def build_provider(
    settings: ModelSettings,
    *,
    environ: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
) -> ModelProvider:
    """Build the provider for one validated configuration."""
    if settings.provider == "environment":
        return model_provider_from_config(environ)
    if settings.provider == "mock":
        return DeterministicMockProvider()
    if settings.provider == "disabled":
        return DisabledModelProvider()
    if settings.provider not in REMOTE_PROVIDERS:
        raise ModelConfigurationError("unsupported provider")
    return OpenAIChatCompletionsProvider(
        api_key=settings.api_key,
        model=settings.model,
        base_url=settings.base_url,
        timeout_seconds=settings.timeout_seconds,
        client=client,
    )


class RuntimeModelProvider:
    """Delegating provider whose target can be replaced while requests run."""

    def __init__(self, provider: ModelProvider, settings: ModelSettings) -> None:
        self._lock = threading.RLock()
        self._provider = provider
        self._settings = settings

    def snapshot(self) -> ModelSettings:
        with self._lock:
            return self._settings

    def provider(self) -> ModelProvider:
        with self._lock:
            return self._provider

    def swap(self, provider: ModelProvider, settings: ModelSettings) -> None:
        with self._lock:
            self._provider = provider
            self._settings = settings

    def _current(self) -> ModelProvider:
        with self._lock:
            return self._provider

    def generate_diagnosis(self, request: DiagnosisRequest) -> DiagnosisModelOutput:
        return self._current().generate_diagnosis(request)

    def generate_hint(self, request: HintRequest) -> HintModelOutput:
        return self._current().generate_hint(request)

    def check_explanation(self, request: ExplanationCheckRequest) -> ExplanationModelOutput:
        return self._current().check_explanation(request)


class ModelSettingsStore(Protocol):
    persistence: str

    def load(self) -> ModelSettings | None: ...

    def save(self, settings: ModelSettings) -> None: ...

    def clear(self) -> None: ...

    def load_user(self, user_id: str) -> ModelSettings | None: ...

    def save_user(self, user_id: str, settings: ModelSettings) -> None: ...

    def clear_user(self, user_id: str) -> None: ...


class InMemoryModelSettingsStore:
    persistence = "memory"

    def __init__(self) -> None:
        self._settings: ModelSettings | None = None
        self._users: dict[str, ModelSettings] = {}

    def load(self) -> ModelSettings | None:
        return self._settings

    def save(self, settings: ModelSettings) -> None:
        self._settings = settings

    def clear(self) -> None:
        self._settings = None

    def load_user(self, user_id: str) -> ModelSettings | None:
        return self._users.get(user_id)

    def save_user(self, user_id: str, settings: ModelSettings) -> None:
        self._users[user_id] = settings

    def clear_user(self, user_id: str) -> None:
        self._users.pop(user_id, None)


_FILE_VERSION = 2


class FileModelSettingsStore:
    """Plaintext local configuration file readable only by the API user.

    One document holds the shared (teacher) configuration plus one optional
    personal override per user id. The version-1 layout was a single flat
    configuration; it is still read as the shared entry so an existing demo
    volume keeps working.

    This matches the existing git-ignored ``.delivery/live-model.env`` posture.
    Production deployments must keep using the environment (ADR 0010).
    """

    persistence = "file"

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> ModelSettings | None:
        with self._lock:
            document = self._read()
        return self._decode(document.get("shared"))

    def save(self, settings: ModelSettings) -> None:
        with self._lock:
            document = self._read()
            document["shared"] = settings.stored_payload()
            self._write(document)

    def clear(self) -> None:
        with self._lock:
            document = self._read()
            document["shared"] = None
            self._write_or_remove(document)

    def load_user(self, user_id: str) -> ModelSettings | None:
        with self._lock:
            document = self._read()
        return self._decode(document["users"].get(user_id))

    def save_user(self, user_id: str, settings: ModelSettings) -> None:
        with self._lock:
            document = self._read()
            document["users"][user_id] = settings.stored_payload()
            self._write(document)

    def clear_user(self, user_id: str) -> None:
        with self._lock:
            document = self._read()
            if user_id not in document["users"]:
                return
            del document["users"][user_id]
            self._write_or_remove(document)

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"version": _FILE_VERSION, "shared": None, "users": {}}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ModelSettingsStorageError("stored model configuration is unreadable") from exc
        if not isinstance(payload, dict):
            raise ModelSettingsStorageError("stored model configuration is invalid")
        if "version" not in payload:
            # Version 1: a single flat configuration, which was the shared one.
            try:
                legacy = validated_settings(payload)
            except ModelConfigurationError as exc:
                raise ModelSettingsStorageError(
                    "stored model configuration is invalid"
                ) from exc
            return {
                "version": _FILE_VERSION,
                "shared": legacy.stored_payload(),
                "users": {},
            }
        shared = payload.get("shared")
        users = payload.get("users", {})
        if shared is not None and not isinstance(shared, dict):
            raise ModelSettingsStorageError("stored model configuration is invalid")
        if not isinstance(users, dict):
            raise ModelSettingsStorageError("stored model configuration is invalid")
        return {
            "version": _FILE_VERSION,
            "shared": shared,
            "users": {str(key): value for key, value in users.items()},
        }

    def _decode(self, payload: Any) -> ModelSettings | None:
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise ModelSettingsStorageError("stored model configuration is invalid")
        try:
            return validated_settings(payload)
        except ModelConfigurationError as exc:
            raise ModelSettingsStorageError("stored model configuration is invalid") from exc

    def _write(self, document: Mapping[str, Any]) -> None:
        serialized = json.dumps(document, ensure_ascii=True, sort_keys=True)
        temporary = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(serialized)
            os.replace(temporary, self._path)
        except OSError as exc:
            raise ModelSettingsStorageError("model configuration could not be stored") from exc

    def _write_or_remove(self, document: Mapping[str, Any]) -> None:
        if document.get("shared") is None and not document["users"]:
            try:
                self._path.unlink(missing_ok=True)
            except OSError as exc:
                raise ModelSettingsStorageError(
                    "model configuration could not be cleared"
                ) from exc
            return
        self._write(document)


def probe_connection(
    settings: ModelSettings, *, client: httpx.Client | None = None
) -> ProbeOutcome:
    """One minimal request that exercises credentials, model name and endpoint."""
    endpoint = f"{settings.base_url.rstrip('/')}/chat/completions"
    timeout = min(settings.timeout_seconds, 10.0)
    payload = {
        "model": settings.model,
        "max_tokens": 1,
        "stream": False,
        "messages": [{"role": "user", "content": "ping"}],
    }
    http = client or httpx.Client()
    try:
        response = http.post(
            endpoint,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            json=payload,
            timeout=timeout,
        )
    except httpx.TimeoutException:
        return ProbeOutcome("timeout")
    except httpx.HTTPError:
        return ProbeOutcome("transport_error")
    finally:
        if client is None:
            http.close()
    return ProbeOutcome(_probe_status(response.status_code), response.status_code)


def _probe_status(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "ok"
    if status_code in {401, 403}:
        return "invalid_credentials"
    if status_code == 404:
        return "model_or_endpoint_not_found"
    if status_code == 429:
        return "rate_limited"
    if status_code in {400, 422}:
        return "rejected_request"
    return "http_error"


class ModelSettingsService:
    """Owns the shared configuration and the optional per-user overrides."""

    def __init__(
        self,
        runtime: RuntimeModelProvider,
        store: ModelSettingsStore,
        *,
        environment: str | None = None,
        environ: Mapping[str, str] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._runtime = runtime
        self._store = store
        self._environ = environ
        self._client = client
        self._environment = environment if environment else os.environ.get("APP_ENV", "development")
        self._lock = threading.RLock()
        self._user_providers: dict[str, ModelProvider] = {}

    @property
    def persistence(self) -> str:
        return self._store.persistence

    @property
    def environment_locked(self) -> bool:
        return self._environment == "production"

    def snapshot(self) -> ModelSettings:
        return self._runtime.snapshot()

    def provider_for(self, user_id: str | None) -> ModelProvider:
        """Personal override first, shared configuration otherwise.

        A broken personal entry must never take the request down: it falls back
        to the shared provider and logs one warning without the key.
        """
        if not user_id:
            return self._runtime.provider()
        with self._lock:
            cached = self._user_providers.get(user_id)
        if cached is not None:
            return cached
        settings = self.personal_settings(user_id)
        if settings is None:
            return self._runtime.provider()
        try:
            provider = build_provider(settings, environ=self._environ, client=self._client)
        except Exception:
            _LOG.warning(
                "personal model configuration is unusable user=%s; using the shared one",
                user_id,
            )
            return self._runtime.provider()
        with self._lock:
            self._user_providers[user_id] = provider
        return provider

    def personal_settings(self, user_id: str) -> ModelSettings | None:
        try:
            return self._store.load_user(user_id)
        except ModelSettingsStorageError:
            _LOG.warning(
                "personal model configuration is unreadable user=%s; using the shared one",
                user_id,
            )
            return None

    def apply(self, payload: Mapping[str, Any]) -> ModelSettings:
        self._require_editable()
        settings = validated_settings(self._inherit_key(payload))
        provider = build_provider(settings, environ=self._environ, client=self._client)
        self._store.save(settings)
        self._runtime.swap(provider, settings)
        _LOG.info(
            "model provider configured provider=%s model=%s source=%s",
            settings.provider,
            settings.model,
            settings.source,
        )
        return settings

    def apply_personal(self, user_id: str, payload: Mapping[str, Any]) -> ModelSettings:
        self._require_editable()
        settings = validated_settings(self._inherit_personal_key(user_id, payload))
        provider = build_provider(settings, environ=self._environ, client=self._client)
        self._store.save_user(user_id, settings)
        with self._lock:
            self._user_providers[user_id] = provider
        _LOG.info(
            "personal model provider configured user=%s provider=%s model=%s",
            user_id,
            settings.provider,
            settings.model,
        )
        return settings

    def clear_personal(self, user_id: str) -> None:
        self._require_editable()
        self._store.clear_user(user_id)
        with self._lock:
            self._user_providers.pop(user_id, None)
        _LOG.info("personal model provider removed user=%s", user_id)

    def restore_environment(self) -> ModelSettings:
        self._require_editable()
        settings = replace(settings_from_environment(self._environ), source="environment")
        provider = build_provider(settings, environ=self._environ, client=self._client)
        self._store.clear()
        self._runtime.swap(provider, settings)
        _LOG.info("model provider restored from the environment")
        return settings

    def probe(self, payload: Mapping[str, Any]) -> ProbeOutcome:
        self._require_editable()
        settings = validated_settings(self._inherit_key(payload))
        if not settings.is_remote:
            raise ModelConfigurationError("connection test needs a remote provider")
        return probe_connection(settings, client=self._client)

    def probe_personal(self, user_id: str, payload: Mapping[str, Any]) -> ProbeOutcome:
        self._require_editable()
        settings = validated_settings(self._inherit_personal_key(user_id, payload))
        if not settings.is_remote:
            raise ModelConfigurationError("connection test needs a remote provider")
        return probe_connection(settings, client=self._client)

    def _inherit_key(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Changing only the model must not force the operator to paste the key again."""
        data = dict(payload)
        if str(data.get("api_key") or "").strip():
            return data
        current = self._runtime.snapshot()
        requested = str(data.get("provider") or "").strip().lower()
        if current.is_remote and current.api_key and current.provider == requested:
            data["api_key"] = current.api_key
        return data

    def _inherit_personal_key(
        self, user_id: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        """A personal key is only ever reused from that same user's entry.

        A student must not be able to silently borrow the teacher's credential
        by selecting the same provider and leaving the key empty: that path is
        the explicit "use the teacher's configuration" mode instead.
        """
        data = dict(payload)
        data.pop("mode", None)
        requested = str(data.get("provider") or "").strip().lower()
        if requested == "environment":
            raise ModelConfigurationError(
                "personal configuration must name a provider, not the environment"
            )
        if str(data.get("api_key") or "").strip():
            return data
        current = self.personal_settings(user_id)
        if current is not None and current.is_remote and current.api_key:
            if current.provider == requested:
                data["api_key"] = current.api_key
        return data

    def _require_editable(self) -> None:
        if self.environment_locked:
            raise ModelConfigurationLocked(
                "model configuration is managed by the environment in production"
            )


class UserScopedModelProvider:
    """Provider seam handed to the services; resolves the target per user."""

    def __init__(self, service: ModelSettingsService) -> None:
        self._service = service

    def for_user(self, user_id: str | None) -> ModelProvider:
        return self._service.provider_for(user_id)

    def generate_diagnosis(self, request: DiagnosisRequest) -> DiagnosisModelOutput:
        return self.for_user(None).generate_diagnosis(request)

    def generate_hint(self, request: HintRequest) -> HintModelOutput:
        return self.for_user(None).generate_hint(request)

    def check_explanation(self, request: ExplanationCheckRequest) -> ExplanationModelOutput:
        return self.for_user(None).check_explanation(request)
