"""In-process migration must preserve the application's sanitized diagnostics."""
import logging
from tests.integration.wave3_support import upgrade
from tests.model_gateway.test_openai_responses import test_untrusted_provider_request_id_is_redacted as sanitized_failure

def test_migration_preserves_sanitized_provider_failure_logging(caplog,monkeypatch):
    logger=logging.getLogger('app.model_gateway.openai_responses')
    monkeypatch.setattr(logger,'disabled',False)
    upgrade()
    # A migration can replace root handlers; pytest reattaches its handler at
    # the next test setup. Do the same to examine this single combined boundary.
    logging.getLogger().addHandler(caplog.handler)
    sanitized_failure(caplog)
