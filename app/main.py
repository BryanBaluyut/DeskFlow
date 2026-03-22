import asyncio
import pathlib
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette_csrf import CSRFMiddleware
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import DataError

from app.config import settings
from app.database import engine, async_session
from app.logging_config import setup_logging, get_logger
from app.middleware import SecurityHeadersMiddleware, RequestIDMiddleware
from app.models import Base, SystemSetting
from app.rate_limit import limiter
from app.auth.dependencies import RedirectToLogin
from app.routes import auth, tickets, admin
from app.routes.knowledge_base import router as kb_router, public_router as kb_public_router
from app.routes.api import router as api_router
from app.routes.chat import router as chat_router, public_chat_router
from app.routes.customer_portal import router as portal_router
from app.routes.web_forms import router as forms_router
from app.routes.reporting import router as reporting_router
from app.routes.ical import router as ical_router
from app.routes.health import router as health_router
from app.routes.setup import router as setup_router
from app.services.email_inbound import poll_imap
from app.services.automation import run_schedulers, check_sla_escalations

# Initialize structured logging
setup_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run Alembic migrations (production) or create_all (development)
    if settings.is_sqlite and not settings.is_production:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info("database_tables_created", mode="create_all")
    else:
        from alembic.config import Config
        from alembic import command
        alembic_cfg = Config("alembic.ini")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: command.upgrade(alembic_cfg, "head"))
        log.info("database_migrated", mode="alembic")

    # Load branding
    async with async_session() as db:
        from sqlalchemy import select as sa_select
        for key in ("product_name", "primary_color", "custom_css"):
            result = await db.execute(sa_select(SystemSetting).where(SystemSetting.key == key))
            setting = result.scalar_one_or_none()
            if setting and setting.value:
                if key == "product_name":
                    app.state.app_name = setting.value
                elif key == "primary_color":
                    app.state.primary_color = setting.value
                elif key == "custom_css":
                    app.state.custom_css = setting.value

    # Start background tasks
    tasks = [
        asyncio.create_task(poll_imap()),
        asyncio.create_task(run_schedulers()),
        asyncio.create_task(check_sla_escalations()),
    ]
    log.info("background_tasks_started", count=len(tasks))
    yield
    for t in tasks:
        t.cancel()
    log.info("application_shutdown")


app = FastAPI(
    title="DeskFlow",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs" if not settings.is_production else None,
    redoc_url="/api/redoc" if not settings.is_production else None,
)

# Default branding (updated from DB in lifespan)
app.state.app_name = "DeskFlow"
app.state.primary_color = "#2563eb"
app.state.custom_css = ""

# State for rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Middleware (order matters — outermost first)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CSRFMiddleware,
    secret=settings.SECRET_KEY,
    exempt_urls=[re.compile(r"/api/.*"), re.compile(r"/health"), re.compile(r"/auth/callback"), re.compile(r"/chat/widget.*"), re.compile(r"/forms/.*")],
    cookie_secure=settings.is_production,
    cookie_samesite="lax",
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    same_site="lax",
    https_only=settings.is_production,
    max_age=86400,  # 24 hours
)
cors_origins = settings.ALLOWED_HOSTS.split(",") if settings.ALLOWED_HOSTS != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=settings.ALLOWED_HOSTS != "*",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RedirectToLogin)
async def redirect_to_login(request: Request, exc: RedirectToLogin):
    return RedirectResponse(url="/auth/login")


@app.exception_handler(PydanticValidationError)
async def pydantic_validation_handler(request: Request, exc: PydanticValidationError):
    from fastapi.responses import JSONResponse
    errors = [{"field": e.get("loc", [])[-1] if e.get("loc") else "", "message": e.get("msg", "")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(DataError)
async def db_data_error_handler(request: Request, exc: DataError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422, content={"detail": "Invalid parameter value"})


@app.exception_handler(OverflowError)
async def overflow_error_handler(request: Request, exc: OverflowError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422, content={"detail": "Numeric value out of range"})


# Templates
template_dir = pathlib.Path(__file__).parent / "templates"
app.state.templates = Jinja2Templates(directory=str(template_dir))

# Static files
static_dir = pathlib.Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Health check (no auth)
app.include_router(health_router)

# Public routes (must be before authenticated chat routes)
app.include_router(kb_public_router)
app.include_router(public_chat_router)
app.include_router(forms_router)

# Setup wizard (no auth, redirects away if setup already done)
app.include_router(setup_router)

# Authenticated routes
app.include_router(auth.router)
app.include_router(tickets.router)
app.include_router(admin.router)
app.include_router(kb_router)
app.include_router(chat_router)
app.include_router(portal_router)
app.include_router(reporting_router)

# API routes
app.include_router(api_router)
app.include_router(ical_router)
