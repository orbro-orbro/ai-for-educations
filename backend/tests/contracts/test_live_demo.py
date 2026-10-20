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


def test_one_click_cmd_starts_live_demo_without_printing_secrets():
    cmd = (ROOT / "start-live-demo.cmd").read_text(encoding="utf-8")
    launcher = (ROOT / "scripts/start-live-demo.ps1").read_text(encoding="utf-8")
    assert "start-live-demo.ps1" in cmd
    assert "-ExecutionPolicy Bypass" in cmd
    assert "API_PORT" not in cmd
    for secret in ("DEEPSEEK_API_KEY", "QWEN_API_KEY", "DEMO_PASSWORD"):
        assert secret not in cmd
    assert "Start-Process" in launcher and "http://127.0.0.1:5309" in launcher
    assert "notepad" in launcher.lower()
    assert not re.search(r"Start-Process[^\n]*API_KEY", launcher)


def test_live_launcher_rejects_inherited_environment_overrides_of_every_config_key():
    launcher = (ROOT / "scripts/start-live-demo.ps1").read_text(encoding="utf-8")
    assert "@($taskConfig.Keys)" in launcher and "foreach($taskKey in $taskGuardKeys)" in launcher
    for sensitive in ("MODEL_BASE_URL", "DEEPSEEK_API_KEY", "QWEN_API_KEY", "MODEL_PROVIDER"):
        assert f"'{sensitive}'" in launcher
    assert "GetEnvironmentVariable($taskKey,'Process')" in launcher
    assert "Inherited environment conflicts with live demo configuration" in launcher
    # The guard must run before Compose can interpolate host variables.
    assert launcher.index("Inherited environment conflicts") < launcher.index("docker @taskCompose") if "docker @taskCompose" in launcher else launcher.index("Inherited environment conflicts") < launcher.index("& docker")
    assert "MODEL_BASE_URL" in launcher
    # The error must name only the key, never its value.
    assert not re.search(r"Inherited environment conflicts[^\n]*\$taskInherited", launcher)


def test_mock_delivery_launcher_is_untouched_and_still_disabled():
    source = (ROOT / "scripts/start-delivery.ps1").read_text(encoding="utf-8")
    assert "'MODEL_PROVIDER','disabled'" in source
