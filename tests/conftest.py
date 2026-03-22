import os

# Force SQLite for tests before any app imports
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENTRA_CLIENT_ID", "")
os.environ.setdefault("ENTRA_CLIENT_SECRET", "")
os.environ.setdefault("ENTRA_TENANT_ID", "")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("LOG_FORMAT", "console")

import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"
