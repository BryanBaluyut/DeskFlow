from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.entra import oauth
from app.config import settings
from app.database import get_db
from app.models import User, UserRole

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login(request: Request):
    if not settings.ENTRA_CLIENT_ID:
        # Show login page when Entra not configured
        return request.app.state.templates.TemplateResponse("login.html", {"request": request})
    redirect_uri = f"{settings.APP_URL}/auth/callback"
    return await oauth.entra.authorize_redirect(request, redirect_uri)


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


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/auth/login", status_code=302)
