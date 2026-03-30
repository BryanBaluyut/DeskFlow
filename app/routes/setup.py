from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password, validate_password
from app.database import get_db
from app.models import User, UserRole

router = APIRouter(tags=["setup"])


async def _has_users(db: AsyncSession) -> bool:
    result = await db.execute(select(User.id).limit(1))
    return result.first() is not None


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request, db: AsyncSession = Depends(get_db)):
    if await _has_users(db):
        return RedirectResponse(url="/auth/login", status_code=302)
    return request.app.state.templates.TemplateResponse("setup.html", {"request": request})


@router.post("/setup")
async def setup_create(
    request: Request,
    display_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if await _has_users(db):
        return RedirectResponse(url="/auth/login", status_code=302)

    errors = []
    if not display_name.strip():
        errors.append("Display name is required.")
    if not email.strip() or "@" not in email:
        errors.append("A valid email is required.")
    pwd_errors = validate_password(password)
    if pwd_errors:
        errors.extend(pwd_errors)
    if password != password_confirm:
        errors.append("Passwords do not match.")

    if errors:
        return request.app.state.templates.TemplateResponse("setup.html", {
            "request": request,
            "errors": errors,
            "display_name": display_name,
            "email": email,
        })

    user = User(
        display_name=display_name.strip(),
        email=email.strip().lower(),
        password_hash=hash_password(password),
        auth_method="local",
        role=UserRole.admin,
        active=True,
        verified=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    request.session["user_id"] = user.id

    # Signal middleware that setup is complete
    request.app.state.setup_complete = True

    return RedirectResponse(url="/", status_code=302)
