"""First-run setup wizard."""
import bcrypt
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.database import get_db
from app.models import User, UserRole, Group, SystemSetting

router = APIRouter(prefix="/setup", tags=["setup"])


async def _needs_setup(db: AsyncSession) -> bool:
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == "setup_complete")
    )
    if result.scalar_one_or_none():
        return False
    # Also check if there are zero users (fresh install)
    user_result = await db.execute(select(User.id).limit(1))
    return user_result.first() is None


async def _setup_in_progress(db: AsyncSession) -> bool:
    """Setup started (has users) but not marked complete."""
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == "setup_complete")
    )
    return result.scalar_one_or_none() is None


@router.get("/", response_class=HTMLResponse)
async def setup_wizard(request: Request, db: AsyncSession = Depends(get_db)):
    # If setup is done, go to dashboard
    complete = await db.execute(
        select(SystemSetting).where(SystemSetting.key == "setup_complete")
    )
    if complete.scalar_one_or_none():
        return RedirectResponse(url="/", status_code=302)

    step = int(request.query_params.get("step", "1"))

    # Step 1 only available if no users yet
    user_result = await db.execute(select(User.id).limit(1))
    has_users = user_result.first() is not None
    if has_users and step == 1:
        step = 2  # Skip to step 2 if admin already created

    # Steps 2+ require authenticated session
    if has_users and not request.session.get("user_id"):
        return RedirectResponse(url="/auth/login", status_code=302)

    return request.app.state.templates.TemplateResponse("setup/wizard.html", {
        "request": request, "step": step,
    })


@router.post("/step1")
async def setup_step1(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Only allow if truly no users
    user_result = await db.execute(select(User.id).limit(1))
    if user_result.first() is not None:
        return RedirectResponse(url="/setup/?step=2", status_code=302)

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    user = User(
        entra_oid=f"local-{email}",
        email=email,
        display_name=display_name,
        role=UserRole.admin,
        password_hash=password_hash,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    request.session["user_id"] = user.id
    return RedirectResponse(url="/setup/?step=2", status_code=302)


@router.post("/step2")
async def setup_step2(
    request: Request,
    product_name: str = Form("DeskFlow"),
    primary_color: str = Form("#2563eb"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    for key, value in [("product_name", product_name), ("primary_color", primary_color)]:
        result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = value
        else:
            db.add(SystemSetting(key=key, value=value))
    await db.commit()
    return RedirectResponse(url="/setup/?step=3", status_code=302)


@router.post("/step3")
async def setup_step3(
    request: Request,
    group_name: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    group = Group(
        name=group_name.strip().lower().replace(" ", "_"),
        display_name=group_name.strip(),
    )
    db.add(group)
    await db.flush()

    user.groups.append(group)

    await db.commit()
    return RedirectResponse(url="/setup/?step=4", status_code=302)


@router.post("/step4")
async def setup_step4(request: Request, user: User = Depends(require_admin)):
    return RedirectResponse(url="/setup/?step=5", status_code=302)


@router.get("/complete")
async def setup_complete(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    db.add(SystemSetting(key="setup_complete", value="true"))
    await db.commit()
    return RedirectResponse(url="/", status_code=302)
