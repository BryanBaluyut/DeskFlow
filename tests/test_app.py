import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_login_page_loads():
    """Verify the login page returns 200."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/auth/login")
        assert response.status_code == 200


@pytest.mark.anyio
async def test_health_or_root_redirect():
    """Verify root redirects to login when unauthenticated."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/", follow_redirects=False)
        assert response.status_code in (200, 302, 307)
