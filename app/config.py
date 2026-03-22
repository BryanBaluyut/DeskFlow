from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Application ---
    SECRET_KEY: str = "change-me"
    APP_URL: str = "http://localhost:8000"
    ENVIRONMENT: str = "development"  # development, staging, production
    ALLOWED_HOSTS: str = "*"

    # --- Entra ID ---
    ENTRA_CLIENT_ID: str = ""
    ENTRA_CLIENT_SECRET: str = ""
    ENTRA_TENANT_ID: str = ""

    # --- IMAP ---
    IMAP_HOST: str = "outlook.office365.com"
    IMAP_PORT: int = 993
    IMAP_USER: str = ""
    IMAP_PASSWORD: str = ""
    EMAIL_POLL_INTERVAL: int = 60

    # --- SMTP ---
    SMTP_HOST: str = "smtp.office365.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_FROM_NAME: str = "IT Help Desk"

    # --- Database ---
    DATABASE_URL: str = "postgresql+asyncpg://deskflow:deskflow@localhost:5432/deskflow"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 300

    # --- Logging ---
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # json or console

    # --- Authentication ---
    LOCAL_AUTH_ENABLED: bool = True
    INVITE_EXPIRY_DAYS: int = 7

    # --- Rate Limiting ---
    RATE_LIMIT_DEFAULT: str = "60/minute"
    RATE_LIMIT_LOGIN: str = "5/minute"
    RATE_LIMIT_API: str = "120/minute"

    @property
    def entra_openid_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.ENTRA_TENANT_ID}/v2.0/.well-known/openid-configuration"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
