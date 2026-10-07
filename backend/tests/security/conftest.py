import pytest
from .security_support import build_harness


@pytest.fixture
def security_app():
    return build_harness()
