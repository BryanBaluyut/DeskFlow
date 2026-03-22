"""Reporting and time accounting exports."""
import csv
import io
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_agent
from app.database import get_db
from app.models import (
    Ticket, TicketStatus, TicketPriority, User, UserRole,
    Group, TimeEntry, TimeAccountingType,
)

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/", response_class=HTMLResponse)
async def reports_dashboard(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_agent)):
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)

    # Ticket counts by status
    status_counts = {}
    for status in TicketStatus:
        count = (await db.execute(
            select(func.count(Ticket.id)).where(Ticket.status == status)
        )).scalar()
        status_counts[status.value] = count

    # Tickets created in last 30 days
    created_30d = (await db.execute(
        select(func.count(Ticket.id)).where(Ticket.created_at >= thirty_days_ago)
    )).scalar()

    # Tickets closed in last 30 days
    closed_30d = (await db.execute(
        select(func.count(Ticket.id)).where(
            Ticket.closed_at >= thirty_days_ago, Ticket.closed_at.isnot(None)
        )
    )).scalar()

    # Average resolution time (closed tickets in last 30 days)
    # Tickets by priority
    priority_counts = {}
    for p in TicketPriority:
        count = (await db.execute(
            select(func.count(Ticket.id)).where(Ticket.priority == p)
        )).scalar()
        priority_counts[p.value] = count

    # Tickets by group
    group_counts = []
    groups = (await db.execute(select(Group))).scalars().all()
    for g in groups:
        count = (await db.execute(
            select(func.count(Ticket.id)).where(Ticket.group_id == g.id)
        )).scalar()
        group_counts.append({"name": g.display_name, "count": count})

    # Top agents by tickets closed
    agent_stats = []
    agents = (await db.execute(
        select(User).where(User.role.in_([UserRole.agent, UserRole.admin]))
    )).scalars().all()
    for agent in agents:
        closed = (await db.execute(
            select(func.count(Ticket.id)).where(
                Ticket.assignee_id == agent.id,
                Ticket.status == TicketStatus.closed,
            )
        )).scalar()
        assigned = (await db.execute(
            select(func.count(Ticket.id)).where(Ticket.assignee_id == agent.id)
        )).scalar()
        agent_stats.append({
            "name": agent.display_name, "closed": closed, "assigned": assigned,
        })

    # Total time accounted
    total_time = (await db.execute(select(func.sum(TimeEntry.time_minutes)))).scalar() or 0

    return request.app.state.templates.TemplateResponse("reports/dashboard.html", {
        "request": request, "user": user,
        "status_counts": status_counts,
        "priority_counts": priority_counts,
        "group_counts": group_counts,
        "agent_stats": agent_stats,
        "created_30d": created_30d,
        "closed_30d": closed_30d,
        "total_time": total_time,
    })


@router.get("/time-accounting", response_class=HTMLResponse)
async def time_accounting_report(
    request: Request,
    start_date: str = "",
    end_date: str = "",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent),
):
    q = select(TimeEntry).order_by(TimeEntry.created_at.desc())

    start = None
    end = None
    if start_date:
        start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        q = q.where(TimeEntry.created_at >= start)
    if end_date:
        end = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
        q = q.where(TimeEntry.created_at <= end)

    entries = (await db.execute(q.limit(500))).scalars().all()

    # Group by type
    by_type = {}
    for t in TimeAccountingType:
        by_type[t.value] = 0
    total = 0
    for e in entries:
        by_type[e.activity_type.value] = by_type.get(e.activity_type.value, 0) + e.time_minutes
        total += e.time_minutes

    return request.app.state.templates.TemplateResponse("reports/time_accounting.html", {
        "request": request, "user": user,
        "entries": entries, "by_type": by_type, "total": total,
        "start_date": start_date, "end_date": end_date,
    })


@router.get("/time-accounting/export")
async def export_time_accounting(
    start_date: str = "", end_date: str = "",
    db: AsyncSession = Depends(get_db), user: User = Depends(require_agent),
):
    q = select(TimeEntry).order_by(TimeEntry.created_at.desc())
    if start_date:
        q = q.where(TimeEntry.created_at >= datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc))
    if end_date:
        q = q.where(TimeEntry.created_at <= datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc))

    entries = (await db.execute(q)).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Ticket ID", "User ID", "Minutes", "Activity Type", "Note", "Date"])
    for e in entries:
        writer.writerow([
            e.ticket_id, e.user_id, e.time_minutes,
            e.activity_type.value, e.note,
            e.created_at.isoformat() if e.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        output, media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=time_accounting.csv"},
    )
