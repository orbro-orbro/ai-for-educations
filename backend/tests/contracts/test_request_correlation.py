"""ADR 0007: caller-controlled correlation text never crosses the boundary."""
import re
import anyio
import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from app.api.errors import install_error_handling, error_response


@pytest.mark.parametrize("status", [200, 401, 404, 409, 422, 503])
@pytest.mark.parametrize("inbound", [None, "", "a" * 32, "duplicate-client-id", "PRIVATE_SECRET_SENTINEL", "x" * 8192, "tab\tmarker", "line\nmarker"], ids=["missing", "empty", "valid-looking", "repeated", "secret", "oversized", "tab", "newline"])
def test_server_ids_are_opaque_unique_and_consistent(status, inbound, caplog):
    app = FastAPI()
    install_error_handling(app)

    @app.get("/operation")
    def operation(request: Request):
        return error_response(request, status, "SYNTHETIC_TEST", "Synthetic operation.")

    async def run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic") as client:
            headers = {} if inbound is None else {"X-Request-ID": inbound}
            return [await client.get("/operation", headers=headers) for _ in range(2)]

    responses = anyio.run(run)
    ids = []
    for response in responses:
        assert response.status_code == status
        identifier = response.headers["X-Request-ID"]
        assert re.fullmatch(r"[0-9a-f]{32}", identifier)
        assert identifier != inbound
        assert response.json()["request_id"] == identifier
        if inbound:
            assert inbound not in response.text
            assert inbound not in caplog.text
        ids.append(identifier)
    assert len(set(ids)) == 2
