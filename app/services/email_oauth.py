"""OAuth2 client credentials token acquisition for M365 IMAP/SMTP."""

import logging
import time

import httpx

from app.config import settings

log = logging.getLogger(__name__)

TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
SCOPE = "https://outlook.office365.com/.default"
TOKEN_REFRESH_MARGIN = 300  # re-acquire 5 min before expiry

# In-memory cache: (tenant_id, email_address) -> (access_token, expires_at)
_token_cache: dict[tuple[str, str], tuple[str, float]] = {}


class EmailOAuthError(Exception):
    pass


async def get_oauth2_token(
    email_address: str,
    tenant_id: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> str:
    """Acquire an M365 OAuth2 access token via client credentials flow.

    Uses the global Entra config by default. Parameters allow overriding
    for per-account configurations in the future.
    """
    tenant = tenant_id or settings.ENTRA_TENANT_ID
    cid = client_id or settings.ENTRA_CLIENT_ID
    csecret = client_secret or settings.ENTRA_CLIENT_SECRET

    if not tenant or not cid or not csecret:
        raise EmailOAuthError(
            "OAuth2 email requires ENTRA_TENANT_ID, ENTRA_CLIENT_ID, "
            "and ENTRA_CLIENT_SECRET to be configured"
        )

    cache_key = (tenant, email_address)
    cached = _token_cache.get(cache_key)
    if cached:
        token, expires_at = cached
        if time.time() < expires_at - TOKEN_REFRESH_MARGIN:
            return token

    token_url = TOKEN_URL_TEMPLATE.format(tenant_id=tenant)
    payload = {
        "grant_type": "client_credentials",
        "client_id": cid,
        "client_secret": csecret,
        "scope": SCOPE,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(token_url, data=payload)

    if resp.status_code != 200:
        log.error("OAuth2 token request failed: %s %s", resp.status_code, resp.text)
        raise EmailOAuthError(f"Token request failed with status {resp.status_code}")

    data = resp.json()
    access_token = data["access_token"]
    expires_in = data.get("expires_in", 3600)
    _token_cache[cache_key] = (access_token, time.time() + expires_in)

    log.info("Acquired OAuth2 token for %s (expires in %ds)", email_address, expires_in)
    return access_token


def clear_token_cache():
    """Clear the token cache (useful for testing)."""
    _token_cache.clear()
