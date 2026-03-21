"""iCal feed for pending reminders and escalated tickets."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Ticket, TicketStatus, User

router = APIRouter(prefix="/ical", tags=["ical"])


@router.get("/feed")
async def ical_feed(
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.api_token == token))
    user = result.scalar_one_or_none()
    if not user:
        return Response("Unauthorized", status_code=401)

    tickets = (await db.execute(
        select(Ticket).where(
            Ticket.assignee_id == user.id,
            Ticket.status.in_([
                TicketStatus.pending_reminder,
                TicketStatus.open,
                TicketStatus.in_progress,
            ]),
        )
    )).scalars().all()

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//DeskFlow//Tickets//EN",
        "CALSCALE:GREGORIAN",
    ]

    for t in tickets:
        dt = t.pending_time or t.first_response_escalation_at or t.created_at
        if not dt:
            continue
        dtstr = dt.strftime("%Y%m%dT%H%M%SZ")
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:ticket-{t.id}@deskflow",
            f"DTSTART:{dtstr}",
            f"DTEND:{dtstr}",
            f"SUMMARY:[#{t.number}] {t.subject}",
            f"DESCRIPTION:Status: {t.status.value} | Priority: {t.priority.value}",
            f"STATUS:{'CONFIRMED' if t.escalated else 'TENTATIVE'}",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    return Response("\r\n".join(lines), media_type="text/calendar")
