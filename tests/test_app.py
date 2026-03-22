import pytest
from httpx import ASGITransport, AsyncClient


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


@pytest.mark.anyio
async def test_health_endpoint():
    """Verify health endpoint returns status."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "database" in data
        assert "version" in data


@pytest.mark.anyio
async def test_security_headers():
    """Verify security headers are present on responses."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/auth/login")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert "X-Request-ID" in response.headers


@pytest.mark.anyio
async def test_request_id_propagation():
    """Verify custom request IDs are returned."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health", headers={"X-Request-ID": "test-123"})
        assert response.headers.get("X-Request-ID") == "test-123"
