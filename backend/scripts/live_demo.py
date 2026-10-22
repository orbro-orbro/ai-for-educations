"""Live-model demo composition: synthetic actors/data, real provider, SQL and Runner.

Unlike delivery_demo, no Mock is injected and nothing falls back to one.
"""
import os

LIVE_PROVIDERS = frozenset({"deepseek", "qwen"})


def require_live_provider_name(environ):
    name = environ.get("MODEL_PROVIDER", "").strip().lower()
    if name not in LIVE_PROVIDERS:
        raise ValueError("Live demo requires MODEL_PROVIDER to be one of: " + ", ".join(sorted(LIVE_PROVIDERS)))
    return name


def create_live_app():
    from scripts.delivery_demo import validate_demo_target
    from app.model_gateway.config import model_provider_from_config

    validate_demo_target(os.environ.get("DATABASE_URL", ""), os.environ.get("APP_ENV"), os.environ.get("KNOWBOUND_SYNTHETIC_DEMO"))
    require_live_provider_name(os.environ)
    provider = model_provider_from_config(os.environ)
    from app.main import create_app
    return create_app(model_provider=provider)
