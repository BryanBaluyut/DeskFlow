from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SECRET_KEY: str = "change-me"
    APP_URL: str = "http://localhost:8000"

    # Entra ID
    ENTRA_CLIENT_ID: str = ""
    ENTRA_CLIENT_SECRET: str = ""
    ENTRA_TENANT_ID: str = ""

    # IMAP
    IMAP_HOST: str = "outlook.office365.com"
    IMAP_PORT: int = 993
    IMAP_USER: str = ""
    IMAP_PASSWORD: str = ""
    EMAIL_POLL_INTERVAL: int = 60

    # SMTP
    SMTP_HOST: str = "smtp.office365.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_FROM_NAME: str = "IT Help Desk"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///data/deskflow.db"

    @property
    def entra_openid_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.ENTRA_TENANT_ID}/v2.0/.well-known/openid-configuration"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
