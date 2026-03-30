from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.entra import oauth
from app.auth.passwords import verify_password
from app.config import settings
from app.database import get_db
from app.models import User, UserRole

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return request.app.state.templates.TemplateResponse("login.html", {
        "request": request,
        "entra_configured": bool(settings.ENTRA_CLIENT_ID),
    })


@router.post("/login")
async def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    error = "Invalid email or password."
    result = await db.execute(
        select(User).where(User.email == email.strip().lower(), User.active == True)
    )
    user = result.scalar_one_or_none()

    if not user or not user.password_hash:
        return request.app.state.templates.TemplateResponse("login.html", {
            "request": request,
            "error": error,
            "email": email,
            "entra_configured": bool(settings.ENTRA_CLIENT_ID),
        })

    if not verify_password(password, user.password_hash):
        return request.app.state.templates.TemplateResponse("login.html", {
            "request": request,
            "error": error,
            "email": email,
            "entra_configured": bool(settings.ENTRA_CLIENT_ID),
        })

    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=302)


@router.get("/login/entra")
async def login_entra(request: Request):
    if not settings.ENTRA_CLIENT_ID:
        return RedirectResponse(url="/auth/login", status_code=302)
    redirect_uri = f"{settings.APP_URL}/auth/callback"
    return await oauth.entra.authorize_redirect(request, redirect_uri)


@router.api_route("/callback", methods=["GET", "POST"])
async def callback(request: Request, db: AsyncSession = Depends(get_db)):
    token = await oauth.entra.authorize_access_token(request)
    userinfo = token.get("userinfo", {})

    oid = userinfo.get("oid") or userinfo.get("sub", "")
    email = userinfo.get("email") or userinfo.get("preferred_username", "")
    name = userinfo.get("name", email)

    # Look up by OID first, then fall back to email match
    result = await db.execute(select(User).where(User.entra_oid == oid))
    user = result.scalar_one_or_none()

    if not user and email:
        result = await db.execute(select(User).where(User.email == email.lower()))
        user = result.scalar_one_or_none()

    if user:
        user.entra_oid = oid
        user.email = email
        user.display_name = name
        # Preserve existing role — never downgrade on SSO login
    else:
        count_result = await db.execute(select(User.id).limit(1))
        is_first = count_result.first() is None
        user = User(
            entra_oid=oid,
            email=email,
            display_name=name,
            auth_method="oauth",
            role=UserRole.admin if is_first else UserRole.customer,
        )
        db.add(user)

    user.last_login = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)

    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/auth/login", status_code=302)
