from authlib.integrations.starlette_client import OAuth
from app.config import settings

oauth = OAuth()

oauth.register(
    name="entra",
    client_id=settings.ENTRA_CLIENT_ID,
    client_secret=settings.ENTRA_CLIENT_SECRET,
    server_metadata_url=settings.entra_openid_url,
    client_kwargs={"scope": "openid email profile"},
)
