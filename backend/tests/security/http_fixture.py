"""Loopback-only HTTP fixture for Playwright; never deploy or collect as pytest."""
import os

# Do this before importing app.main's module-level application. An inherited
# database/provider configuration must never connect this fixture to real data.
os.environ["APP_ENV"] = "test"
os.environ["MODEL_PROVIDER"] = "mock"
os.environ.pop("DATABASE_URL", None)
os.environ["AUTH_TOKEN_SECRET"] = "task10-http-fixture-synthetic-secret"

from .security_support import build_harness

app = build_harness().app
