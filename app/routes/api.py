"""REST API endpoints for DeskFlow - JSON API for integrations."""
import secrets
from datetime import datetime, timedelta, timezone

import bleach
from fastapi import APIRouter, Depends, HTTPException, Header, Path, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import (
    Article, Ticket, TicketPriority, TicketStatus, TicketChannel,
    User, UserRole, Group, Tag, Organization, TextModule,
    Notification, TriggerEvent,
)
from app.services.automation import fire_triggers
from app.services.ticket_service import generate_ticket_number, record_history, apply_sla, notify_mentions

from app.rate_limit import limiter

router = APIRouter(prefix="/api/v1", tags=["api"])

_SAFE_TAGS = ["p", "br", "b", "i", "u", "a", "ul", "ol", "li", "pre", "code", "strong", "em", "blockquote", "h1", "h2", "h3", "h4", "img", "table", "thead", "tbody", "tr", "th", "td"]
_SAFE_ATTRS = {"a": ["href", "title"], "img": ["src", "alt", "width", "height"]}


def _sanitize(html: str) -> str:
    return bleach.clean(html, tags=_SAFE_TAGS, attributes=_SAFE_ATTRS, strip=True)


def _strip_tags(text: str) -> str:
    cleaned = bleach.clean(text, tags=[], strip=True)
    return cleaned.replace('"', '&quot;').replace("'", '&#x27;')


def _sanitize_custom_fields(fields: dict) -> dict:
    if not fields:
        return {}
    sanitized = {}
    for k, v in fields.items():
        key = str(k).strip()
        if not key:
            continue  # Skip empty keys (#79)
        sanitized[key] = v
    return sanitized


async def get_api_user(
    authorization: str = Header(None),
    x_api_token: str = Header(None, alias="X-API-Token"),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = x_api_token
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    if not token:
        raise HTTPException(401, "API token required")
    result = await db.execute(select(User).where(User.api_token == token, User.active == True))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(401, "Invalid API token")
    user.api_token_last_used = datetime.now(timezone.utc)
    return user


def ticket_to_dict(t: Ticket) -> dict:
    return {
        "id": t.id, "number": t.number, "subject": t.subject,
        "body_html": t.body_html, "status": t.status.value,
        "priority": t.priority.value, "channel": t.channel.value if t.channel else None,
        "group_id": t.group_id, "creator_id": t.creator_id,
        "assignee_id": t.assignee_id, "organization_id": t.organization_id,
        "sla_id": t.sla_id, "escalated": t.escalated,
        "time_spent": t.time_spent,
        "tags": [tag.name for tag in t.tags] if t.tags else [],
        "custom_fields": t.custom_fields or {},
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
    }


def user_to_dict(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "display_name": u.display_name,
        "firstname": u.firstname, "lastname": u.lastname,
        "role": u.role.value, "active": u.active, "vip": u.vip,
        "organization_id": u.organization_id,
        "custom_fields": u.custom_fields or {},
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


# --- Tickets ---

class TicketCreate(BaseModel):
    subject: str = Field(..., min_length=1, max_length=500)
    body: str = Field(default="", max_length=100000)
    priority: str = "medium"
    group_id: int | None = None
    tags: list[str] = []
    custom_fields: dict = {}
    channel: str = "api"

    @field_validator("custom_fields")
    @classmethod
    def validate_custom_fields_size(cls, v: dict) -> dict:
        import json
        if len(json.dumps(v)) > 10240:
            raise ValueError("custom_fields exceeds 10KB limit")
        return v


class TicketUpdate(BaseModel):
    status: str | None = None
    priority: str | None = None
    assignee_id: int | None = None
    group_id: int | None = None
    custom_fields: dict | None = None

    @field_validator("custom_fields")
    @classmethod
    def validate_custom_fields_size(cls, v: dict | None) -> dict | None:
        import json
        if v is not None and len(json.dumps(v)) > 10240:
            raise ValueError("custom_fields exceeds 10KB limit")
        return v


class ArticleCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=100000)
    is_internal: bool = False


@router.get("/tickets")
@limiter.limit("120/minute")
async def list_tickets(
    request: Request,
    page: int = 1, per_page: int = 25,
    status: str | None = None, group_id: int | None = None,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_api_user),
):
    if page < 1:
        raise HTTPException(422, "page must be >= 1")
    if page > 1000000:
        raise HTTPException(422, "page value too large")
    if per_page < 1 or per_page > 100:
        raise HTTPException(422, "per_page must be between 1 and 100")
    q = select(Ticket).options(selectinload(Ticket.tags))
    if user.role == UserRole.customer:
        q = q.where(Ticket.creator_id == user.id)
    if status:
        try:
            TicketStatus(status)
        except ValueError:
            raise HTTPException(422, f"Invalid status filter. Must be one of: {', '.join(e.value for e in TicketStatus)}")
        q = q.where(Ticket.status == status)
    if group_id:
        q = q.where(Ticket.group_id == group_id)
    q = q.order_by(Ticket.updated_at.desc()).offset((page - 1) * per_page).limit(per_page)
    tickets = (await db.execute(q)).scalars().all()
    return {"data": [ticket_to_dict(t) for t in tickets], "page": page}


@router.get("/tickets/{ticket_id}")
async def get_ticket(
    ticket_id: int = Path(..., le=2147483647),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_api_user),
):
    ticket = await db.get(Ticket, ticket_id, options=[
        selectinload(Ticket.tags), selectinload(Ticket.articles),
    ])
    if not ticket:
        raise HTTPException(404)
    if user.role == UserRole.customer and ticket.creator_id != user.id:
        raise HTTPException(403)
    data = ticket_to_dict(ticket)
    data["articles"] = [{
        "id": a.id, "body_html": a.body_html, "is_internal": a.is_internal,
        "author_id": a.author_id, "channel": a.channel.value if a.channel else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    } for a in ticket.articles if not a.is_internal or user.role != UserRole.customer]
    return {"data": data}


@router.post("/tickets", status_code=201)
@limiter.limit("30/minute")
async def create_ticket(
    request: Request,
    payload: TicketCreate,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_api_user),
):
    number = await generate_ticket_number(db)
    try:
        priority = TicketPriority(payload.priority)
    except ValueError:
        raise HTTPException(422, f"Invalid priority. Must be one of: {', '.join(e.value for e in TicketPriority)}")
    try:
        channel = TicketChannel(payload.channel) if payload.channel else TicketChannel.api
    except ValueError:
        raise HTTPException(422, f"Invalid channel. Must be one of: {', '.join(e.value for e in TicketChannel)}")
    if payload.group_id:
        group = await db.get(Group, payload.group_id)
        if not group:
            raise HTTPException(404, "Group not found")
    ticket = Ticket(
        number=number, subject=_strip_tags(payload.subject), body_html=_sanitize(payload.body),
        priority=priority, creator_id=user.id,
        group_id=payload.group_id,
        channel=channel,
        custom_fields=_sanitize_custom_fields(payload.custom_fields),
    )
    db.add(ticket)
    await db.flush()

    article = Article(
        ticket_id=ticket.id, author_id=user.id, body_html=_sanitize(payload.body),
        channel=TicketChannel.api,
        sender="customer" if user.role == UserRole.customer else "agent",
    )
    db.add(article)

    # Load tags relationship for M2M append
    result = await db.execute(
        select(Ticket).options(selectinload(Ticket.tags)).where(Ticket.id == ticket.id)
    )
    ticket = result.scalar_one()

    for tag_name in payload.tags:
        result = await db.execute(select(Tag).where(Tag.name == tag_name))
        tag = result.scalar_one_or_none()
        if not tag:
            tag = Tag(name=tag_name)
            db.add(tag)
            await db.flush()
        ticket.tags.append(tag)

    await apply_sla(db, ticket)
    await record_history(db, ticket.id, user.id, "created")
    await db.commit()
    result = await db.execute(
        select(Ticket).options(selectinload(Ticket.tags)).where(Ticket.id == ticket.id)
    )
    ticket = result.scalar_one()
    await fire_triggers(db, ticket, TriggerEvent.ticket_create)
    await db.commit()
    return {"data": ticket_to_dict(ticket)}


@router.put("/tickets/{ticket_id}")
async def update_ticket(
    ticket_id: int = Path(..., le=2147483647), *, payload: TicketUpdate,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_api_user),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404)
    if user.role == UserRole.customer:
        raise HTTPException(403)

    if ticket.merged_into_id and payload.status:
        raise HTTPException(400, "Cannot change status of a merged ticket")

    if payload.status:
        try:
            ticket.status = TicketStatus(payload.status)
        except ValueError:
            raise HTTPException(422, f"Invalid status. Must be one of: {', '.join(e.value for e in TicketStatus)}")
        if payload.status == "closed":
            ticket.closed_at = datetime.now(timezone.utc)
        elif payload.status != "closed":
            ticket.closed_at = None
        if ticket.status == TicketStatus.pending_reminder and not ticket.pending_time:
            ticket.pending_time = datetime.now(timezone.utc) + timedelta(days=1)
        if ticket.status != TicketStatus.pending_reminder:
            ticket.pending_time = None
    if payload.priority:
        try:
            ticket.priority = TicketPriority(payload.priority)
        except ValueError:
            raise HTTPException(422, f"Invalid priority. Must be one of: {', '.join(e.value for e in TicketPriority)}")
    if payload.assignee_id is not None:
        if payload.assignee_id:
            assignee = await db.get(User, payload.assignee_id)
            if not assignee:
                raise HTTPException(404, "Assignee not found")
            if assignee.role == UserRole.customer:
                raise HTTPException(400, "Cannot assign ticket to a customer")
            if not assignee.active:
                raise HTTPException(400, "Cannot assign ticket to a deactivated user")
        ticket.assignee_id = payload.assignee_id or None
    if payload.group_id is not None:
        if payload.group_id:
            group = await db.get(Group, payload.group_id)
            if not group:
                raise HTTPException(404, "Group not found")
        ticket.group_id = payload.group_id or None
    if payload.custom_fields is not None:
        ticket.custom_fields = _sanitize_custom_fields(payload.custom_fields)

    if payload.status:
        await record_history(db, ticket_id, user.id, "updated", "status", None, payload.status)
    if payload.priority:
        await record_history(db, ticket_id, user.id, "updated", "priority", None, payload.priority)
    if payload.assignee_id is not None:
        await record_history(db, ticket_id, user.id, "updated", "assignee_id", None, str(payload.assignee_id or ""))
    if payload.group_id is not None:
        await record_history(db, ticket_id, user.id, "updated", "group_id", None, str(payload.group_id or ""))

    await fire_triggers(db, ticket, TriggerEvent.ticket_update)
    await db.commit()
    result = await db.execute(
        select(Ticket).options(selectinload(Ticket.tags)).where(Ticket.id == ticket.id)
    )
    ticket = result.scalar_one()
    return {"data": ticket_to_dict(ticket)}


@router.post("/tickets/{ticket_id}/articles", status_code=201)
async def create_article(
    ticket_id: int = Path(..., le=2147483647), *, payload: ArticleCreate,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_api_user),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404)
    if user.role == UserRole.customer and ticket.creator_id != user.id:
        raise HTTPException(403)

    article = Article(
        ticket_id=ticket_id, author_id=user.id, body_html=_sanitize(payload.body),
        is_internal=payload.is_internal and user.role != UserRole.customer,
        channel=TicketChannel.api,
        sender="customer" if user.role == UserRole.customer else "agent",
    )
    db.add(article)
    await db.flush()

    # Reopen resolved/pending tickets on customer reply
    if user.role == UserRole.customer and ticket.status in (TicketStatus.resolved, TicketStatus.pending_close):
        ticket.status = TicketStatus.open
        ticket.closed_at = None

    await notify_mentions(db, ticket_id, payload.body, user.id)
    await db.commit()
    return {"data": {"id": article.id, "ticket_id": ticket_id}}


# --- Users ---

@router.get("/users")
async def list_users(
    page: int = 1, per_page: int = 25,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_api_user),
):
    if user.role != UserRole.admin:
        raise HTTPException(403, "Admin access required")
    q = select(User).order_by(User.display_name).offset((page - 1) * per_page).limit(per_page)
    users = (await db.execute(q)).scalars().all()
    return {"data": [user_to_dict(u) for u in users]}


@router.get("/users/me")
async def get_me(user: User = Depends(get_api_user)):
    return {"data": user_to_dict(user)}


@router.get("/users/{user_id}")
async def get_user(user_id: int = Path(..., le=2147483647), db: AsyncSession = Depends(get_db), user: User = Depends(get_api_user)):
    if user.role == UserRole.customer and user.id != user_id:
        raise HTTPException(403)
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404)
    return {"data": user_to_dict(target)}


# --- Groups ---

@router.get("/groups")
async def list_groups(db: AsyncSession = Depends(get_db), user: User = Depends(get_api_user)):
    if user.role == UserRole.customer:
        raise HTTPException(403, "Access denied")
    groups = (await db.execute(select(Group).where(Group.active == True))).scalars().all()
    return {"data": [{"id": g.id, "name": g.name, "display_name": g.display_name} for g in groups]}


# --- Organizations ---

@router.get("/organizations")
async def list_organizations(db: AsyncSession = Depends(get_db), user: User = Depends(get_api_user)):
    if user.role == UserRole.customer:
        raise HTTPException(403)
    orgs = (await db.execute(select(Organization))).scalars().all()
    return {"data": [{"id": o.id, "name": o.name, "domain": o.domain, "domain_assignment": o.domain_assignment, "vip": o.vip, "custom_fields": o.custom_fields or {}} for o in orgs]}


# --- Tags ---

@router.get("/tags")
async def list_tags(db: AsyncSession = Depends(get_db), user: User = Depends(get_api_user)):
    if user.role == UserRole.customer:
        raise HTTPException(403, "Access denied")
    tags = (await db.execute(select(Tag).order_by(Tag.name))).scalars().all()
    return {"data": [{"id": t.id, "name": t.name} for t in tags]}


# --- Text Modules ---

@router.get("/text-modules")
async def list_text_modules(db: AsyncSession = Depends(get_db), user: User = Depends(get_api_user)):
    if user.role == UserRole.customer:
        raise HTTPException(403)
    modules = (await db.execute(select(TextModule).where(TextModule.active == True))).scalars().all()
    return {"data": [{"id": m.id, "name": m.name, "keyword": m.keyword, "content": m.content} for m in modules]}


# --- Notifications ---

@router.get("/notifications")
async def list_notifications(db: AsyncSession = Depends(get_db), user: User = Depends(get_api_user)):
    result = await db.execute(
        select(Notification).where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc()).limit(50)
    )
    notifications = result.scalars().all()
    return {"data": [{
        "id": n.id, "type": n.notification_type.value, "message": n.message,
        "ticket_id": n.ticket_id, "seen": n.seen,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    } for n in notifications]}


@router.post("/notifications/mark-all-read")
async def mark_all_read(db: AsyncSession = Depends(get_db), user: User = Depends(get_api_user)):
    result = await db.execute(
        select(Notification).where(Notification.user_id == user.id, Notification.seen == False)
    )
    for n in result.scalars().all():
        n.seen = True
    await db.commit()
    return {"status": "ok"}


# --- API Token Management ---

@router.post("/token/generate")
@limiter.limit("3/minute")
async def generate_token(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_api_user)):
    old_token_prefix = user.api_token[:8] + "..." if user.api_token else None
    user.api_token = secrets.token_urlsafe(32)
    await db.commit()
    return {"data": {"token": user.api_token, "previous_token_prefix": old_token_prefix, "warning": "Previous token has been invalidated"}}


# --- Stats ---

@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db), user: User = Depends(get_api_user)):
    if user.role == UserRole.customer:
        raise HTTPException(403)

    total = (await db.execute(select(func.count()).select_from(Ticket))).scalar() or 0
    open_count = (await db.execute(
        select(func.count()).select_from(Ticket).where(Ticket.status.in_([TicketStatus.open, TicketStatus.in_progress]))
    )).scalar() or 0
    closed = (await db.execute(
        select(func.count()).select_from(Ticket).where(Ticket.status == TicketStatus.closed)
    )).scalar() or 0
    escalated = (await db.execute(
        select(func.count()).select_from(Ticket).where(Ticket.escalated == True)
    )).scalar() or 0

    return {"data": {
        "total_tickets": total, "open_tickets": open_count,
        "closed_tickets": closed, "escalated_tickets": escalated,
    }}
