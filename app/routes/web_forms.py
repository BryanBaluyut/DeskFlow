"""Public web form submission endpoint."""
import bleach
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    WebForm, Ticket, Article, TicketChannel, User, UserRole,
)
from app.rate_limit import limiter
from app.services.ticket_service import generate_ticket_number

router = APIRouter(prefix="/forms", tags=["forms"])


@router.get("/", response_class=HTMLResponse)
async def forms_index(request: Request):
    raise HTTPException(404, "Please provide a form ID in the URL: /forms/{form_id}")


@router.get("/{form_id}", response_class=HTMLResponse)
async def render_form(form_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    form = await db.get(WebForm, form_id)
    if not form or not form.active:
        raise HTTPException(404)
    return request.app.state.templates.TemplateResponse("forms/public_form.html", {
        "request": request, "form": form,
    })


@router.post("/{form_id}/submit")
@limiter.limit("10/minute")
async def submit_form(form_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    form = await db.get(WebForm, form_id)
    if not form or not form.active:
        raise HTTPException(404)

    data = await request.form()
    name = bleach.clean(data.get("name", "Anonymous"), tags=[], strip=True)
    email = bleach.clean(data.get("email", ""), tags=[], strip=True)
    subject = bleach.clean(data.get("subject", "Web Form Submission"), tags=[], strip=True)
    message = bleach.clean(data.get("message", ""), tags=[], strip=True)

    if not name or not email or not subject or not message:
        raise HTTPException(422, "All fields are required")

    # Find or create user by email
    user = None
    if email:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
    if not user:
        user = User(
            entra_oid=f"form-{email or name}",
            email=email or f"form-{name}@unknown",
            display_name=name,
            role=UserRole.customer,
        )
        db.add(user)
        await db.flush()

    number = await generate_ticket_number(db)
    ticket = Ticket(
        number=number, subject=subject, body_html=bleach.clean(message, tags=[], strip=True),
        creator_id=user.id, group_id=form.group_id,
        channel=TicketChannel.form,
    )
    db.add(ticket)
    await db.flush()

    article = Article(
        ticket_id=ticket.id, author_id=user.id,
        body_html=f"<p><strong>From:</strong> {name} ({email})</p><p>{message}</p>",
        channel=TicketChannel.form, sender="customer",
    )
    db.add(article)
    await db.commit()

    return request.app.state.templates.TemplateResponse("forms/success.html", {
        "request": request, "form": form, "ticket_number": ticket.number,
    })
