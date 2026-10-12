import pytest
import socket
from urllib.request import urlopen

from tests.integration.wave3_environment import DATABASES, validate_target
from tests.integration.wave3_support import postgres_url, runner_endpoint
from sqlalchemy.engine import make_url


@pytest.mark.parametrize("database", DATABASES)
def test_gate_initializer_accepts_only_its_labeled_test_databases(database):
    validate_target({"com.docker.compose.project": "knowbound-wave3-gate", "knowbound.task": "wave3-integration-gate"}, database)


@pytest.mark.parametrize("labels,database", [
    ({"com.docker.compose.project": "knowbound-cj", "knowbound.task": "wave3-integration-gate"}, "wave3_browser"),
    ({"com.docker.compose.project": "knowbound-wave3-gate"}, "wave3_browser"),
    ({"com.docker.compose.project": "knowbound-wave3-gate", "knowbound.task": "wave3-integration-gate"}, "knowbound"),
    ({"com.docker.compose.project": "knowbound-wave3-gate", "knowbound.task": "wave3-integration-gate"}, "wave3_browser; DROP DATABASE knowbound"),
])
def test_gate_initializer_rejects_daily_resources_and_unlisted_database_names(labels, database):
    with pytest.raises(ValueError):
        validate_target(labels, database)


def test_gate_services_are_reachable_over_loopback():
    target = make_url(postgres_url())
    with socket.create_connection((target.host, target.port), timeout=3):
        pass
    with urlopen(runner_endpoint() + "/health", timeout=3) as response:
        assert response.status == 200
