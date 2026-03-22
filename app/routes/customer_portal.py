"""Customer portal - dedicated interface for customers."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models import (
    Article, Ticket, TicketPriority, TicketStatus, TicketChannel,
    User, KBArticle, ArticleVisibility,
)
from app.schemas import PortalTicketCreateForm, PortalReplyForm, ProfileUpdateForm
from app.services.ticket_service import generate_ticket_number, record_history

router = APIRouter(prefix="/portal", tags=["customer_portal"])


@router.get("/", response_class=HTMLResponse)
async def portal_home(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    my_tickets = (await db.execute(
        select(Ticket).where(Ticket.creator_id == user.id)
        .options(selectinload(Ticket.assignee), selectinload(Ticket.group))
        .order_by(Ticket.updated_at.desc()).limit(10)
    )).scalars().all()

    # Featured KB articles
    featured_articles = (await db.execute(
        select(KBArticle).where(KBArticle.visibility == ArticleVisibility.public)
        .options(selectinload(KBArticle.category))
        .order_by(KBArticle.updated_at.desc()).limit(5)
    )).scalars().all()

    return request.app.state.templates.TemplateResponse("portal/home.html", {
        "request": request, "user": user, "tickets": my_tickets,
        "featured_articles": featured_articles,
    })


@router.get("/tickets", response_class=HTMLResponse)
async def portal_tickets(
    request: Request, status: str | None = None,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    q = select(Ticket).where(Ticket.creator_id == user.id).options(
        selectinload(Ticket.assignee), selectinload(Ticket.group),
    )
    if status:
        q = q.where(Ticket.status == status)
    q = q.order_by(Ticket.updated_at.desc())
    tickets = (await db.execute(q)).scalars().all()

    return request.app.state.templates.TemplateResponse("portal/tickets.html", {
        "request": request, "user": user, "tickets": tickets,
        "filter_status": status, "statuses": list(TicketStatus),
    })


@router.get("/tickets/new", response_class=HTMLResponse)
async def portal_new_ticket(request: Request, user: User = Depends(get_current_user)):
    return request.app.state.templates.TemplateResponse("portal/new_ticket.html", {
        "request": request, "user": user, "priorities": list(TicketPriority),
    })


@router.post("/tickets/new")
async def portal_create_ticket(
    request: Request,
    subject: str = Form(...), body: str = Form(""), priority: str = Form("medium"),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    form = PortalTicketCreateForm(subject=subject, body=body, priority=priority)
    number = await generate_ticket_number(db)
    ticket = Ticket(
        number=number, subject=form.subject,
        body_html=form.body,
        priority=TicketPriority(form.priority), creator_id=user.id,
        channel=TicketChannel.web,
    )
    db.add(ticket)
    await db.flush()

    article = Article(
        ticket_id=ticket.id, author_id=user.id,
        body_html=form.body,
        channel=TicketChannel.web, sender="customer",
    )
    db.add(article)
    await record_history(db, ticket.id, user.id, "created")
    await db.commit()
    return RedirectResponse(url=f"/portal/tickets/{ticket.id}", status_code=302)


@router.get("/tickets/{ticket_id}", response_class=HTMLResponse)
async def portal_ticket_detail(
    request: Request, ticket_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    ticket = await db.get(Ticket, ticket_id, options=[
        selectinload(Ticket.creator), selectinload(Ticket.assignee),
        selectinload(Ticket.articles).selectinload(Article.author),
    ])
    if not ticket or ticket.creator_id != user.id:
        raise HTTPException(404)

    articles = [a for a in ticket.articles if not a.is_internal]

    return request.app.state.templates.TemplateResponse("portal/ticket_detail.html", {
        "request": request, "user": user, "ticket": ticket, "articles": articles,
    })


@router.post("/tickets/{ticket_id}/reply")
async def portal_reply(
    ticket_id: int, body: str = Form(...),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    form = PortalReplyForm(body=body)
    ticket = await db.get(Ticket, ticket_id)
    if not ticket or ticket.creator_id != user.id:
        raise HTTPException(404)

    article = Article(
        ticket_id=ticket_id, author_id=user.id,
        body_html=form.body,
        channel=TicketChannel.web, sender="customer",
    )
    db.add(article)

    # Reopen if resolved
    if ticket.status in (TicketStatus.resolved, TicketStatus.pending_close):
        ticket.status = TicketStatus.open

    # Notify assigned agent
    if ticket.assignee_id:
        from app.models import NotificationType
        from app.services.ticket_service import create_notification
        await create_notification(
            db, ticket.assignee_id, NotificationType.ticket_update, ticket_id,
            f"Customer replied on ticket #{ticket.number}",
        )

    await db.commit()
    return RedirectResponse(url=f"/portal/tickets/{ticket_id}", status_code=302)


@router.get("/profile", response_class=HTMLResponse)
async def portal_profile(request: Request, user: User = Depends(get_current_user)):
    return request.app.state.templates.TemplateResponse("portal/profile.html", {
        "request": request, "user": user,
    })


@router.post("/profile")
async def portal_update_profile(
    request: Request,
    display_name: str = Form(...),
    phone: str = Form(""),
    locale: str = Form("en"),
    timezone: str = Form("UTC"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    form = ProfileUpdateForm(display_name=display_name, phone=phone, locale=locale, timezone=timezone)
    user.display_name = form.display_name
    user.phone = form.phone or None
    user.locale = form.locale
    user.timezone = form.timezone
    await db.commit()
    return RedirectResponse(url="/portal/profile", status_code=302)
