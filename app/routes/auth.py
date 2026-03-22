import bcrypt
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.dependencies import require_admin
from app.auth.entra import oauth
from app.config import settings
from app.database import get_db
from app.models import User, UserRole

from app.rate_limit import limiter

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    local_auth = settings.LOCAL_AUTH_ENABLED or not settings.ENTRA_CLIENT_ID
    sso_enabled = bool(settings.ENTRA_CLIENT_ID)

    # If only SSO and no local auth, redirect directly to SSO
    if sso_enabled and not local_auth:
        redirect_uri = f"{settings.APP_URL}/auth/callback"
        return await oauth.entra.authorize_redirect(request, redirect_uri)

    return request.app.state.templates.TemplateResponse("login.html", {
        "request": request,
        "local_auth": local_auth,
        "sso_enabled": sso_enabled,
        "error": request.query_params.get("error", ""),
    })


@router.get("/callback")
async def callback(request: Request, db: AsyncSession = Depends(get_db)):
    token = await oauth.entra.authorize_access_token(request)
    userinfo = token.get("userinfo", {})

    oid = userinfo.get("oid") or userinfo.get("sub", "")
    email = userinfo.get("email") or userinfo.get("preferred_username", "")
    name = userinfo.get("name", email)

    result = await db.execute(select(User).where(User.entra_oid == oid))
    user = result.scalar_one_or_none()

    if user:
        user.email = email
        user.display_name = name
    else:
        # First user becomes admin
        count_result = await db.execute(select(User.id).limit(1))
        is_first = count_result.first() is None
        user = User(
            entra_oid=oid,
            email=email,
            display_name=name,
            role=UserRole.admin if is_first else UserRole.customer,
        )
        db.add(user)

    await db.commit()
    await db.refresh(user)

    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=302)


@router.post("/login")
@limiter.limit("5/minute")
async def local_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not settings.LOCAL_AUTH_ENABLED and settings.ENTRA_CLIENT_ID:
        raise HTTPException(403, "Local authentication is disabled")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash:
        return request.app.state.templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid email or password",
            "local_auth": settings.LOCAL_AUTH_ENABLED or not settings.ENTRA_CLIENT_ID,
            "sso_enabled": bool(settings.ENTRA_CLIENT_ID),
        })

    if not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
        return request.app.state.templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid email or password",
            "local_auth": settings.LOCAL_AUTH_ENABLED or not settings.ENTRA_CLIENT_ID,
            "sso_enabled": bool(settings.ENTRA_CLIENT_ID),
        })

    if not user.active:
        return request.app.state.templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Account is disabled. Contact your administrator.",
            "local_auth": settings.LOCAL_AUTH_ENABLED or not settings.ENTRA_CLIENT_ID,
            "sso_enabled": bool(settings.ENTRA_CLIENT_ID),
        })

    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=302)


@router.get("/sso")
async def sso_login(request: Request):
    if not settings.ENTRA_CLIENT_ID:
        return RedirectResponse(url="/auth/login?error=SSO+is+not+configured")
    redirect_uri = f"{settings.APP_URL}/auth/callback"
    return await oauth.entra.authorize_redirect(request, redirect_uri)


@router.post("/admin/reset-password/{user_id}")
async def admin_reset_password(
    user_id: int,
    new_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404)
    hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    target.password_hash = hashed
    await db.commit()
    return RedirectResponse(url="/admin/", status_code=302)


@router.get("/invite/{token}", response_class=HTMLResponse)
async def accept_invite_form(request: Request, token: str, db: AsyncSession = Depends(get_db)):
    from app.models import Invitation
    result = await db.execute(select(Invitation).where(Invitation.token == token))
    invitation = result.scalar_one_or_none()

    if not invitation:
        return request.app.state.templates.TemplateResponse("login.html", {
            "request": request, "error": "Invalid invitation link",
            "local_auth": True, "sso_enabled": bool(settings.ENTRA_CLIENT_ID),
        })

    if invitation.accepted:
        return request.app.state.templates.TemplateResponse("login.html", {
            "request": request, "error": "This invitation has already been used",
            "local_auth": True, "sso_enabled": bool(settings.ENTRA_CLIENT_ID),
        })

    if invitation.expires_at < datetime.now(timezone.utc):
        return request.app.state.templates.TemplateResponse("login.html", {
            "request": request, "error": "This invitation has expired",
            "local_auth": True, "sso_enabled": bool(settings.ENTRA_CLIENT_ID),
        })

    return request.app.state.templates.TemplateResponse("auth/accept_invite.html", {
        "request": request, "invitation": invitation, "token": token,
    })


@router.post("/invite/{token}")
async def accept_invite(
    request: Request, token: str,
    display_name: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    from app.models import Invitation

    result = await db.execute(select(Invitation).where(Invitation.token == token))
    invitation = result.scalar_one_or_none()

    if not invitation or invitation.accepted or invitation.expires_at < datetime.now(timezone.utc):
        return RedirectResponse(url="/auth/login?error=Invalid+or+expired+invitation", status_code=302)

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    user = User(
        entra_oid=f"local-{invitation.email}",
        email=invitation.email,
        display_name=display_name,
        role=invitation.role,
        password_hash=password_hash,
        organization_id=invitation.organization_id,
    )
    db.add(user)
    invitation.accepted = True
    await db.commit()
    await db.refresh(user)

    # Add to group if specified
    if invitation.group_id:
        from app.models import Group
        group = await db.get(Group, invitation.group_id)
        if group:
            user.groups.append(group)
            await db.commit()

    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/auth/login", status_code=302)
