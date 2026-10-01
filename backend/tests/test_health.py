import anyio
from httpx import ASGITransport, AsyncClient

from app.main import app


def test_health_reports_service_ready() -> None:
    async def get_health():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get("/health")

    response = anyio.run(get_health)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "knowbound-api"}
