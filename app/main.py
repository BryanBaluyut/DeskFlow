import asyncio
import logging
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates

from app.config import settings
from app.database import engine
from app.models import Base
from app.auth.dependencies import RedirectToLogin
from app.routes import auth, tickets, admin
from app.routes.knowledge_base import router as kb_router, public_router as kb_public_router
from app.routes.api import router as api_router
from app.routes.chat import router as chat_router, public_chat_router
from app.routes.customer_portal import router as portal_router
from app.routes.web_forms import router as forms_router
from app.routes.reporting import router as reporting_router
from app.routes.ical import router as ical_router
from app.services.email_inbound import poll_imap
from app.services.automation import run_schedulers, check_sla_escalations

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("Database tables created")

    # Start background tasks
    tasks = [
        asyncio.create_task(poll_imap()),
        asyncio.create_task(run_schedulers()),
        asyncio.create_task(check_sla_escalations()),
    ]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="DeskFlow", version="1.0.0", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)


@app.exception_handler(RedirectToLogin)
async def redirect_to_login(request: Request, exc: RedirectToLogin):
    return RedirectResponse(url="/auth/login")


# Templates
template_dir = pathlib.Path(__file__).parent / "templates"
app.state.templates = Jinja2Templates(directory=str(template_dir))

# Static files
static_dir = pathlib.Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Authenticated routes
app.include_router(auth.router)
app.include_router(tickets.router)
app.include_router(admin.router)
app.include_router(kb_router)
app.include_router(chat_router)
app.include_router(portal_router)
app.include_router(reporting_router)

# Public routes (no auth)
app.include_router(kb_public_router)
app.include_router(public_chat_router)
app.include_router(forms_router)

# API routes
app.include_router(api_router)
app.include_router(ical_router)
