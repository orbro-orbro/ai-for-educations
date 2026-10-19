"""Live-model demo stack: separate from the Mock delivery demo and fail-fast."""
from pathlib import Path
import re

import pytest

from scripts.live_demo import require_live_provider_name

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("name", ["", "disabled", "mock", "openai", "teleagent", "unknown"])
def test_live_demo_rejects_non_live_providers(name):
    with pytest.raises(ValueError):
        require_live_provider_name({"MODEL_PROVIDER": name})


@pytest.mark.parametrize("name", ["deepseek", "qwen"])
def test_live_demo_accepts_supported_live_providers(name):
    assert require_live_provider_name({"MODEL_PROVIDER": name.upper()}) == name


def test_live_compose_is_isolated_from_mock_delivery_stack():
    compose = (ROOT / "infra/compose/docker-compose.live-model.yml").read_text(encoding="utf-8")
    launcher = (ROOT / "scripts/start-live-demo.ps1").read_text(encoding="utf-8")
    assert "knowbound-live-demo" in launcher and "knowbound.task: live-model-demo" in compose
    for shared in ("knowbound-wave4-demo", "wave4-task11-demo", "5209", "8208"):
        assert shared not in compose and shared not in launcher
    assert "scripts.live_demo:create_live_app" in compose
    assert "DeliveryMockProvider" not in compose
    assert re.search(r"VITE_MODEL_LABEL", compose)


def test_live_launcher_fails_fast_without_keys_and_never_echoes_them():
    launcher = (ROOT / "scripts/start-live-demo.ps1").read_text(encoding="utf-8")
    assert ".delivery/live-model.env" in launcher
    for key in ("DEEPSEEK_API_KEY", "QWEN_API_KEY", "MODEL_NAME"):
        assert key in launcher
    assert "must be configured" in launcher
    assert not re.search(r"Write-(Output|Host)[^\n]*API_KEY\]?\)?\s*\$", launcher)
    assert "Remove-Item" not in launcher and "volume rm" not in launcher
    assert "MODEL_PROVIDER=mock" not in launcher


def test_mock_delivery_launcher_is_untouched_and_still_disabled():
    source = (ROOT / "scripts/start-delivery.ps1").read_text(encoding="utf-8")
    assert "'MODEL_PROVIDER','disabled'" in source
