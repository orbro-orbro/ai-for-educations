import anyio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def _preflight(origin: str):
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://testserver"
    ) as client:
        return await client.options(
            "/auth/login",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )


def test_local_frontend_origin_can_preflight_login() -> None:
    response = anyio.run(_preflight, "http://127.0.0.1:5173")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "content-type" in response.headers["access-control-allow-headers"].lower()


def test_localhost_frontend_origin_can_preflight_login() -> None:
    response = anyio.run(_preflight, "http://localhost:5173")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_unlisted_origin_cannot_preflight_login() -> None:
    response = anyio.run(_preflight, "https://untrusted.example")

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
