"""Tests for OAuth2 email token service and notification routing."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def clear_cache():
    """Ensure token cache is clean before each test."""
    from app.services.email_oauth import clear_token_cache
    clear_token_cache()
    yield
    clear_token_cache()


@pytest.fixture
def anyio_backend():
    return "asyncio"


# --- OAuth2 Token Tests ---


@pytest.mark.anyio
async def test_get_oauth2_token_success():
    """Token acquisition returns access_token from M365 response."""
    from app.services.email_oauth import get_oauth2_token

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "test-token-123",
        "expires_in": 3600,
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.email_oauth.httpx.AsyncClient", return_value=mock_client), \
         patch("app.services.email_oauth.settings") as mock_settings:
        mock_settings.ENTRA_TENANT_ID = "test-tenant"
        mock_settings.ENTRA_CLIENT_ID = "test-client-id"
        mock_settings.ENTRA_CLIENT_SECRET = "test-secret"

        token = await get_oauth2_token("support@company.com")
        assert token == "test-token-123"

        # Verify correct endpoint was called
        call_args = mock_client.post.call_args
        assert "test-tenant" in call_args[0][0]
        assert call_args[1]["data"]["grant_type"] == "client_credentials"
        assert call_args[1]["data"]["scope"] == "https://outlook.office365.com/.default"


@pytest.mark.anyio
async def test_get_oauth2_token_cached():
    """Second call uses cached token instead of making HTTP request."""
    from app.services.email_oauth import get_oauth2_token, _token_cache

    _token_cache[("test-tenant", "support@company.com")] = (
        "cached-token", time.time() + 3600
    )

    with patch("app.services.email_oauth.settings") as mock_settings:
        mock_settings.ENTRA_TENANT_ID = "test-tenant"
        mock_settings.ENTRA_CLIENT_ID = "test-client-id"
        mock_settings.ENTRA_CLIENT_SECRET = "test-secret"

        token = await get_oauth2_token("support@company.com")
        assert token == "cached-token"


@pytest.mark.anyio
async def test_get_oauth2_token_expired_cache():
    """Expired cached token triggers a new request."""
    from app.services.email_oauth import get_oauth2_token, _token_cache

    # Cache an expired token
    _token_cache[("test-tenant", "support@company.com")] = (
        "old-token", time.time() - 100
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "new-token",
        "expires_in": 3600,
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.email_oauth.httpx.AsyncClient", return_value=mock_client), \
         patch("app.services.email_oauth.settings") as mock_settings:
        mock_settings.ENTRA_TENANT_ID = "test-tenant"
        mock_settings.ENTRA_CLIENT_ID = "test-client-id"
        mock_settings.ENTRA_CLIENT_SECRET = "test-secret"

        token = await get_oauth2_token("support@company.com")
        assert token == "new-token"


@pytest.mark.anyio
async def test_get_oauth2_token_missing_config():
    """Raises EmailOAuthError when Entra config is missing."""
    from app.services.email_oauth import get_oauth2_token, EmailOAuthError

    with patch("app.services.email_oauth.settings") as mock_settings:
        mock_settings.ENTRA_TENANT_ID = ""
        mock_settings.ENTRA_CLIENT_ID = ""
        mock_settings.ENTRA_CLIENT_SECRET = ""

        with pytest.raises(EmailOAuthError, match="ENTRA_TENANT_ID"):
            await get_oauth2_token("support@company.com")


@pytest.mark.anyio
async def test_get_oauth2_token_http_error():
    """Raises EmailOAuthError on non-200 response."""
    from app.services.email_oauth import get_oauth2_token, EmailOAuthError

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "invalid_client"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.email_oauth.httpx.AsyncClient", return_value=mock_client), \
         patch("app.services.email_oauth.settings") as mock_settings:
        mock_settings.ENTRA_TENANT_ID = "test-tenant"
        mock_settings.ENTRA_CLIENT_ID = "bad-client"
        mock_settings.ENTRA_CLIENT_SECRET = "bad-secret"

        with pytest.raises(EmailOAuthError, match="401"):
            await get_oauth2_token("support@company.com")


# --- Notification Routing Tests ---


def test_make_message_id():
    """Message IDs follow expected format."""
    from app.services.email_outbound import _make_message_id

    assert _make_message_id(42) == "<ticket-42@deskflow>"
    assert _make_message_id(42, 7) == "<ticket-42-article-7@deskflow>"


def test_extract_body_strips_quoted_text():
    """Email body extraction strips quoted reply text."""
    from app.services.email_inbound import _extract_body
    import email as email_mod
    from email import policy as email_policy

    raw = (
        "From: test@example.com\r\n"
        "Subject: Test\r\n"
        "Content-Type: text/plain\r\n"
        "\r\n"
        "This is the reply.\r\n"
        "\r\n"
        "On Mon, Jan 1, 2026 someone wrote:\r\n"
        "> Original message\r\n"
    )
    msg = email_mod.message_from_string(raw, policy=email_policy.default)
    body = _extract_body(msg)
    assert "This is the reply." in body
    assert "Original message" not in body


@pytest.mark.anyio
async def test_send_comment_notification_routes_agent_to_customer():
    """Agent comment should trigger customer notification, not agent."""
    from app.services.email_outbound import send_comment_notification

    ticket = MagicMock()
    ticket.creator = MagicMock(id=10, email="customer@test.com")
    ticket.number = "20260328-0001"
    ticket.subject = "Test"
    ticket.email_message_id = "<ticket-1@deskflow>"
    ticket.group_id = None
    ticket.assignee_id = 5

    article = MagicMock()
    article.sender = "agent"
    article.id = 1
    article.body_html = "We are working on this."

    author = MagicMock(id=5, display_name="Agent Smith", email="agent@test.com")

    with patch("app.services.email_outbound._send_customer_notification", new_callable=AsyncMock) as mock_cust, \
         patch("app.services.email_outbound._send_agent_notification", new_callable=AsyncMock) as mock_agent:
        await send_comment_notification(ticket, article, author, db=None)
        mock_cust.assert_called_once_with(ticket, article, author)
        mock_agent.assert_not_called()


@pytest.mark.anyio
async def test_send_comment_notification_routes_customer_to_agent():
    """Customer comment should trigger agent notification."""
    from app.services.email_outbound import send_comment_notification

    ticket = MagicMock()
    ticket.assignee_id = 5
    ticket.number = "20260328-0001"

    article = MagicMock()
    article.sender = "customer"

    author = MagicMock(id=10, display_name="Customer", email="customer@test.com")

    mock_db = AsyncMock()
    agent_user = MagicMock(id=5, email="agent@test.com", display_name="Agent")
    mock_db.get.return_value = agent_user

    with patch("app.services.email_outbound._send_agent_notification", new_callable=AsyncMock) as mock_agent, \
         patch("app.services.email_outbound._send_customer_notification", new_callable=AsyncMock) as mock_cust:
        await send_comment_notification(ticket, article, author, db=mock_db)
        mock_agent.assert_called_once_with(ticket, article, author, agent_user)
        mock_cust.assert_not_called()
