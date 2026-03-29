import bleach
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user, require_agent
from app.database import get_db
from app.models import (
    Article, Attachment, Ticket, TicketPriority, TicketStatus, TicketChannel,
    User, UserRole, Group, Tag, TicketLink, LinkType,
    Checklist, ChecklistItem, ChecklistItemStatus, ChecklistTemplate,
    Mention, TimeEntry, TimeAccountingType, Macro,
)
from app.services.ticket_service import (
    generate_ticket_number, record_history, create_notification,
    notify_mentions, merge_tickets, split_ticket, apply_sla,
    apply_checklist_template,
)
from app.services.email_outbound import send_ticket_notification, send_comment_notification

router = APIRouter(tags=["tickets"])

ALLOWED_TAGS = ["p", "br", "b", "i", "u", "a", "ul", "ol", "li", "pre", "code", "strong", "em", "blockquote", "h1", "h2", "h3", "h4", "img", "table", "thead", "tbody", "tr", "th", "td"]
ALLOWED_ATTRS = {"a": ["href", "title"], "img": ["src", "alt", "width", "height"]}


def _clean(html: str) -> str:
    return bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    templates = request.app.state.templates

    open_count = (await db.execute(
        select(func.count(Ticket.id)).where(Ticket.status.in_([TicketStatus.open, TicketStatus.in_progress]))
    )).scalar()
    my_count = (await db.execute(
        select(func.count(Ticket.id)).where(Ticket.assignee_id == user.id, Ticket.status != TicketStatus.closed)
    )).scalar()
    unassigned_count = (await db.execute(
        select(func.count(Ticket.id)).where(Ticket.assignee_id.is_(None), Ticket.status == TicketStatus.open)
    )).scalar()
    escalated_count = (await db.execute(
        select(func.count(Ticket.id)).where(Ticket.escalated == True)
    )).scalar()

    if user.role in (UserRole.agent, UserRole.admin):
        q = select(Ticket).options(
            selectinload(Ticket.creator), selectinload(Ticket.assignee),
            selectinload(Ticket.group), selectinload(Ticket.tags),
        ).order_by(Ticket.updated_at.desc()).limit(25)
    else:
        q = select(Ticket).options(
            selectinload(Ticket.creator), selectinload(Ticket.assignee),
            selectinload(Ticket.group), selectinload(Ticket.tags),
        ).where(Ticket.creator_id == user.id).order_by(Ticket.updated_at.desc()).limit(25)

    tickets = (await db.execute(q)).scalars().all()

    # Recent activity for agents
    from app.models import Notification
    notifications = []
    if user.role in (UserRole.agent, UserRole.admin):
        notif_result = await db.execute(
            select(Notification).where(
                Notification.user_id == user.id, Notification.seen == False
            ).order_by(Notification.created_at.desc()).limit(10)
        )
        notifications = notif_result.scalars().all()

    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": user, "tickets": tickets,
        "open_count": open_count, "my_count": my_count,
        "unassigned_count": unassigned_count, "escalated_count": escalated_count,
        "notifications": notifications,
    })


@router.get("/tickets", response_class=HTMLResponse)
async def ticket_list(
    request: Request,
    status: str | None = None,
    assignee: str | None = None,
    group_id: int | None = None,
    priority: str | None = None,
    tag: str | None = None,
    search: str | None = None,
    page: int = 1,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    templates = request.app.state.templates
    q = select(Ticket).options(
        selectinload(Ticket.creator), selectinload(Ticket.assignee),
        selectinload(Ticket.group), selectinload(Ticket.tags),
    )

    if user.role == UserRole.customer:
        q = q.where(Ticket.creator_id == user.id)
    if status:
        q = q.where(Ticket.status == status)
    if priority:
        q = q.where(Ticket.priority == priority)
    if assignee == "me":
        q = q.where(Ticket.assignee_id == user.id)
    elif assignee == "unassigned":
        q = q.where(Ticket.assignee_id.is_(None))
    if group_id:
        q = q.where(Ticket.group_id == group_id)
    if tag:
        q = q.join(Ticket.tags).where(Tag.name == tag)
    if search:
        q = q.where(Ticket.subject.ilike(f"%{search}%") | Ticket.number.ilike(f"%{search}%"))

    per_page = 25
    q = q.order_by(Ticket.updated_at.desc()).offset((page - 1) * per_page).limit(per_page)
    tickets = (await db.execute(q)).scalars().all()

    groups = (await db.execute(select(Group).where(Group.active == True))).scalars().all()
    all_tags = (await db.execute(select(Tag).order_by(Tag.name))).scalars().all()

    return templates.TemplateResponse("ticket_list.html", {
        "request": request, "user": user, "tickets": tickets,
        "filter_status": status, "filter_assignee": assignee,
        "filter_group_id": group_id, "filter_priority": priority,
        "filter_tag": tag, "search": search, "page": page,
        "groups": groups, "all_tags": all_tags,
        "statuses": list(TicketStatus), "priorities": list(TicketPriority),
    })


@router.get("/tickets/new", response_class=HTMLResponse)
async def ticket_create_form(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    groups = (await db.execute(select(Group).where(Group.active == True))).scalars().all()
    templates_list = (await db.execute(
        select(TicketTemplate).where(TicketTemplate.active == True)
    )).scalars().all() if user.role != UserRole.customer else []

    from app.models import TicketTemplate
    return request.app.state.templates.TemplateResponse("ticket_create.html", {
        "request": request, "user": user, "priorities": list(TicketPriority),
        "groups": groups, "ticket_templates": templates_list,
    })


@router.post("/tickets/new")
async def ticket_create(
    request: Request,
    subject: str = Form(...),
    body: str = Form(""),
    priority: str = Form("medium"),
    group_id: int | None = Form(None),
    tags: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    number = await generate_ticket_number(db)
    ticket = Ticket(
        number=number,
        subject=subject.strip(),
        body_html=_clean(body),
        priority=TicketPriority(priority),
        creator_id=user.id,
        group_id=group_id,
        organization_id=user.organization_id if hasattr(user, 'organization_id') else None,
        channel=TicketChannel.web,
    )
    db.add(ticket)
    await db.flush()

    # Initial article
    article = Article(
        ticket_id=ticket.id,
        author_id=user.id,
        body_html=_clean(body),
        channel=TicketChannel.web,
        sender="customer" if user.role == UserRole.customer else "agent",
    )
    db.add(article)

    # Tags
    if tags.strip():
        for tag_name in tags.split(","):
            tag_name = tag_name.strip()
            if not tag_name:
                continue
            result = await db.execute(select(Tag).where(Tag.name == tag_name))
            tag = result.scalar_one_or_none()
            if not tag:
                tag = Tag(name=tag_name)
                db.add(tag)
                await db.flush()
            ticket.tags.append(tag)

    # SLA
    await apply_sla(db, ticket)

    await record_history(db, ticket.id, user.id, "created")
    await db.commit()
    await db.refresh(ticket)
    await send_ticket_notification(ticket, user)
    await notify_mentions(db, ticket.id, body, user.id)
    await db.commit()

    return RedirectResponse(url=f"/tickets/{ticket.id}", status_code=302)


@router.get("/tickets/{ticket_id}", response_class=HTMLResponse)
async def ticket_detail(
    request: Request, ticket_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    ticket = await db.get(Ticket, ticket_id, options=[
        selectinload(Ticket.creator), selectinload(Ticket.assignee),
        selectinload(Ticket.group), selectinload(Ticket.tags),
        selectinload(Ticket.articles).selectinload(Article.author),
        selectinload(Ticket.articles).selectinload(Article.attachments),
        selectinload(Ticket.history).selectinload(TicketHistory.user),
        selectinload(Ticket.checklist).selectinload(Checklist.items),
        selectinload(Ticket.links_from).selectinload(TicketLink.target),
        selectinload(Ticket.links_to).selectinload(TicketLink.source),
        selectinload(Ticket.mentions).selectinload(Mention.user),
        selectinload(Ticket.time_entries),
        selectinload(Ticket.sla),
    ])
    if not ticket:
        raise HTTPException(404)
    if user.role == UserRole.customer and ticket.creator_id != user.id:
        raise HTTPException(403)

    from app.models import TicketHistory
    articles = [a for a in ticket.articles if not a.is_internal or user.role != UserRole.customer]

    agents = []
    groups = []
    macros = []
    checklist_templates = []
    if user.role in (UserRole.agent, UserRole.admin):
        agents = (await db.execute(
            select(User).where(User.role.in_([UserRole.agent, UserRole.admin]), User.active == True)
        )).scalars().all()
        groups = (await db.execute(select(Group).where(Group.active == True))).scalars().all()
        macros = (await db.execute(select(Macro).where(Macro.active == True))).scalars().all()
        checklist_templates = (await db.execute(select(ChecklistTemplate))).scalars().all()

    # Linked tickets
    linked_tickets = []
    for link in ticket.links_from:
        linked_tickets.append({"ticket": link.target, "type": link.link_type.value, "direction": "from"})
    for link in ticket.links_to:
        linked_tickets.append({"ticket": link.source, "type": link.link_type.value, "direction": "to"})

    total_time = sum(e.time_minutes for e in ticket.time_entries)

    return request.app.state.templates.TemplateResponse("ticket_detail.html", {
        "request": request, "user": user, "ticket": ticket,
        "articles": articles, "agents": agents, "groups": groups,
        "statuses": list(TicketStatus), "priorities": list(TicketPriority),
        "macros": macros, "linked_tickets": linked_tickets,
        "checklist_templates": checklist_templates,
        "total_time": total_time,
        "time_types": list(TimeAccountingType),
    })


@router.post("/tickets/{ticket_id}/article")
async def add_article(
    request: Request, ticket_id: int,
    body: str = Form(...),
    is_internal: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ticket = await db.get(Ticket, ticket_id, options=[selectinload(Ticket.creator)])
    if not ticket:
        raise HTTPException(404)
    if user.role == UserRole.customer and ticket.creator_id != user.id:
        raise HTTPException(403)

    article = Article(
        ticket_id=ticket_id,
        author_id=user.id,
        body_html=_clean(body),
        is_internal=is_internal and user.role != UserRole.customer,
        sender="customer" if user.role == UserRole.customer else "agent",
        channel=TicketChannel.web,
    )
    db.add(article)
    await db.flush()

    await record_history(db, ticket_id, user.id, "article_added")

    if not article.is_internal:
        await send_comment_notification(ticket, article, user, db=db)

    await notify_mentions(db, ticket_id, body, user.id)
    await db.commit()

    return RedirectResponse(url=f"/tickets/{ticket_id}", status_code=302)


@router.post("/tickets/{ticket_id}/update")
async def update_ticket(
    request: Request, ticket_id: int,
    status: str | None = Form(None),
    priority: str | None = Form(None),
    assignee_id: str | None = Form(None),
    group_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404)

    from datetime import datetime, timezone
    if status and status != ticket.status.value:
        old = ticket.status.value
        ticket.status = TicketStatus(status)
        if ticket.status == TicketStatus.closed:
            ticket.closed_at = datetime.now(timezone.utc)
        await record_history(db, ticket_id, user.id, "updated", "status", old, status)

    if priority and priority != ticket.priority.value:
        old = ticket.priority.value
        ticket.priority = TicketPriority(priority)
        await record_history(db, ticket_id, user.id, "updated", "priority", old, priority)

    if assignee_id is not None:
        old = str(ticket.assignee_id) if ticket.assignee_id else ""
        new_val = int(assignee_id) if assignee_id else None
        ticket.assignee_id = new_val
        await record_history(db, ticket_id, user.id, "updated", "assignee_id", old, str(new_val or ""))
        if new_val:
            from app.models import NotificationType
            await create_notification(
                db, new_val, NotificationType.ticket_update, ticket_id,
                f"Ticket #{ticket.number} assigned to you",
            )

    if group_id is not None:
        old = str(ticket.group_id) if ticket.group_id else ""
        ticket.group_id = int(group_id) if group_id else None
        await record_history(db, ticket_id, user.id, "updated", "group_id", old, str(group_id or ""))

    await db.commit()
    return RedirectResponse(url=f"/tickets/{ticket_id}", status_code=302)


@router.post("/tickets/{ticket_id}/tags")
async def add_tag(
    ticket_id: int, tag_name: str = Form(...),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_agent),
):
    ticket = await db.get(Ticket, ticket_id, options=[selectinload(Ticket.tags)])
    if not ticket:
        raise HTTPException(404)

    result = await db.execute(select(Tag).where(Tag.name == tag_name.strip()))
    tag = result.scalar_one_or_none()
    if not tag:
        tag = Tag(name=tag_name.strip())
        db.add(tag)
        await db.flush()
    if tag not in ticket.tags:
        ticket.tags.append(tag)
    await db.commit()
    return RedirectResponse(url=f"/tickets/{ticket_id}", status_code=302)


@router.post("/tickets/{ticket_id}/tags/{tag_id}/remove")
async def remove_tag(
    ticket_id: int, tag_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_agent),
):
    ticket = await db.get(Ticket, ticket_id, options=[selectinload(Ticket.tags)])
    tag = await db.get(Tag, tag_id)
    if ticket and tag and tag in ticket.tags:
        ticket.tags.remove(tag)
        await db.commit()
    return RedirectResponse(url=f"/tickets/{ticket_id}", status_code=302)


@router.post("/tickets/{ticket_id}/merge")
async def merge(
    ticket_id: int, target_id: int = Form(...),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_agent),
):
    success = await merge_tickets(db, ticket_id, target_id, user.id)
    if not success:
        raise HTTPException(400, "Could not merge tickets")
    await db.commit()
    return RedirectResponse(url=f"/tickets/{target_id}", status_code=302)


@router.post("/tickets/{ticket_id}/split/{article_id}")
async def split(
    ticket_id: int, article_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_agent),
):
    new_ticket = await split_ticket(db, ticket_id, article_id, user.id)
    if not new_ticket:
        raise HTTPException(400, "Could not split ticket")
    await db.commit()
    return RedirectResponse(url=f"/tickets/{new_ticket.id}", status_code=302)


@router.post("/tickets/{ticket_id}/link")
async def link_ticket(
    ticket_id: int,
    target_id: int = Form(...),
    link_type: str = Form("related"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent),
):
    link = TicketLink(
        source_id=ticket_id, target_id=target_id,
        link_type=LinkType(link_type),
    )
    db.add(link)
    await record_history(db, ticket_id, user.id, "linked", "linked_to", None, str(target_id))
    await db.commit()
    return RedirectResponse(url=f"/tickets/{ticket_id}", status_code=302)


@router.post("/tickets/{ticket_id}/checklist")
async def add_checklist(
    ticket_id: int,
    template_id: int | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent),
):
    if template_id:
        await apply_checklist_template(db, ticket_id, template_id)
    else:
        checklist = Checklist(ticket_id=ticket_id)
        db.add(checklist)
    await db.commit()
    return RedirectResponse(url=f"/tickets/{ticket_id}", status_code=302)


@router.post("/tickets/{ticket_id}/checklist/item")
async def add_checklist_item(
    ticket_id: int, title: str = Form(...),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_agent),
):
    ticket = await db.get(Ticket, ticket_id, options=[selectinload(Ticket.checklist)])
    if not ticket or not ticket.checklist:
        raise HTTPException(404)
    item = ChecklistItem(
        checklist_id=ticket.checklist.id,
        title=title.strip(),
        position=len(ticket.checklist.items) if ticket.checklist.items else 0,
    )
    db.add(item)
    await db.commit()
    return RedirectResponse(url=f"/tickets/{ticket_id}", status_code=302)


@router.post("/tickets/{ticket_id}/checklist/item/{item_id}/toggle")
async def toggle_checklist_item(
    ticket_id: int, item_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_agent),
):
    item = await db.get(ChecklistItem, item_id)
    if not item:
        raise HTTPException(404)
    item.status = (
        ChecklistItemStatus.done if item.status == ChecklistItemStatus.open
        else ChecklistItemStatus.open
    )
    await db.commit()
    return RedirectResponse(url=f"/tickets/{ticket_id}", status_code=302)


@router.post("/tickets/{ticket_id}/time")
async def add_time_entry(
    ticket_id: int,
    time_minutes: float = Form(...),
    activity_type: str = Form("other"),
    note: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404)

    entry = TimeEntry(
        ticket_id=ticket_id, user_id=user.id,
        time_minutes=time_minutes,
        activity_type=TimeAccountingType(activity_type),
        note=note,
    )
    db.add(entry)
    ticket.time_spent = (ticket.time_spent or 0) + time_minutes
    await db.commit()
    return RedirectResponse(url=f"/tickets/{ticket_id}", status_code=302)


@router.post("/tickets/{ticket_id}/macro/{macro_id}")
async def apply_macro(
    ticket_id: int, macro_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_agent),
):
    ticket = await db.get(Ticket, ticket_id)
    macro = await db.get(Macro, macro_id)
    if not ticket or not macro:
        raise HTTPException(404)

    for action in macro.actions or []:
        field = action.get("field")
        value = action.get("value")
        if field == "status":
            ticket.status = TicketStatus(value)
        elif field == "priority":
            ticket.priority = TicketPriority(value)
        elif field == "assignee_id":
            ticket.assignee_id = int(value) if value else None
        elif field == "group_id":
            ticket.group_id = int(value) if value else None

    await record_history(db, ticket_id, user.id, "macro_applied", "macro", None, macro.name)
    await db.commit()
    return RedirectResponse(url=f"/tickets/{ticket_id}", status_code=302)


# Bulk actions
@router.post("/tickets/bulk")
async def bulk_action(
    request: Request,
    ticket_ids: str = Form(...),
    action: str = Form(...),
    value: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent),
):
    ids = [int(x) for x in ticket_ids.split(",") if x.strip()]
    for tid in ids:
        ticket = await db.get(Ticket, tid)
        if not ticket:
            continue
        if action == "status":
            ticket.status = TicketStatus(value)
            await record_history(db, tid, user.id, "bulk_updated", "status", None, value)
        elif action == "priority":
            ticket.priority = TicketPriority(value)
        elif action == "assignee_id":
            ticket.assignee_id = int(value) if value else None
        elif action == "group_id":
            ticket.group_id = int(value) if value else None
        elif action == "close":
            ticket.status = TicketStatus.closed
            from datetime import datetime, timezone
            ticket.closed_at = datetime.now(timezone.utc)

    await db.commit()
    return RedirectResponse(url="/tickets", status_code=302)


# Notifications
@router.get("/notifications", response_class=HTMLResponse)
async def notifications_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.models import Notification
    result = await db.execute(
        select(Notification).where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc()).limit(50)
    )
    notifications = result.scalars().all()
    return request.app.state.templates.TemplateResponse("notifications.html", {
        "request": request, "user": user, "notifications": notifications,
    })


@router.post("/notifications/mark-read")
async def mark_notifications_read(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    from app.models import Notification
    result = await db.execute(
        select(Notification).where(Notification.user_id == user.id, Notification.seen == False)
    )
    for n in result.scalars().all():
        n.seen = True
    await db.commit()
    return RedirectResponse(url="/notifications", status_code=302)


# Import TicketTemplate and TicketHistory for type hints
from app.models import TicketTemplate, TicketHistory
