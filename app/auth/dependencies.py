from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import User, UserRole


class RedirectToLogin(Exception):
    pass


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise RedirectToLogin()
    user = await db.get(User, user_id)
    if not user:
        request.session.clear()
        raise RedirectToLogin()
    return user


async def require_agent(user: User = Depends(get_current_user)) -> User:
    if user.role not in (UserRole.agent, UserRole.admin):
        raise HTTPException(status_code=403, detail="Agent or admin access required")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
