from __future__ import annotations

import os
from collections.abc import Mapping

import httpx

from app.model_gateway.base import ProviderFailure
from app.model_gateway.mock import DeterministicMockProvider
from app.model_gateway.openai_responses import OpenAIResponsesProvider


class DisabledModelProvider:
    @staticmethod
    def _disabled():
        raise ProviderFailure("model provider is disabled")

    def generate_diagnosis(self, _request):
        return self._disabled()

    def generate_hint(self, _request):
        return self._disabled()

    def check_explanation(self, _request):
        return self._disabled()


def model_provider_from_config(environ: Mapping[str, str] | None = None, *, client: httpx.Client | None = None):
    values = os.environ if environ is None else environ
    environment = values.get("APP_ENV", "development")
    provider_name = values.get("MODEL_PROVIDER", "").strip().lower()
    if not provider_name:
        if environment not in {"development", "test"}:
            raise RuntimeError("MODEL_PROVIDER must be configured in production")
        return DisabledModelProvider()
    if provider_name == "mock":
        if environment not in {"development", "test"}:
            raise RuntimeError("mock model provider is forbidden in production")
        return DeterministicMockProvider()
    if provider_name == "disabled":
        if environment not in {"development", "test"}:
            raise RuntimeError("disabled model provider is forbidden in production")
        return DisabledModelProvider()
    if provider_name != "openai":
        raise RuntimeError("unsupported MODEL_PROVIDER")
    api_key = values.get("OPENAI_API_KEY", "")
    model = values.get("MODEL_NAME", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY must be configured for the OpenAI provider")
    if not model:
        raise RuntimeError("MODEL_NAME must be configured for the OpenAI provider")
    try:
        timeout = float(values.get("MODEL_TIMEOUT_SECONDS", "30"))
    except ValueError as exc:
        raise RuntimeError("MODEL_TIMEOUT_SECONDS must be a positive number") from exc
    if timeout <= 0:
        raise RuntimeError("MODEL_TIMEOUT_SECONDS must be a positive number")
    return OpenAIResponsesProvider(api_key=api_key, model=model, base_url=values.get("OPENAI_BASE_URL", "https://api.openai.com"), timeout_seconds=timeout, client=client)
