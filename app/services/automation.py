"""Automation engine: triggers, schedulers, SLA escalation, webhooks."""
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models import (
    Ticket, TicketStatus, TicketPriority, Article, Trigger, TriggerEvent,
    Scheduler, Webhook, Notification, NotificationType,
)

log = logging.getLogger(__name__)


def _match_conditions(ticket: Ticket, conditions: dict) -> bool:
    """Check if a ticket matches trigger/scheduler conditions."""
    for field, expected in conditions.items():
        if field == "status":
            values = expected if isinstance(expected, list) else [expected]
            if ticket.status.value not in values:
                return False
        elif field == "priority":
            values = expected if isinstance(expected, list) else [expected]
            if ticket.priority.value not in values:
                return False
        elif field == "group_id":
            values = expected if isinstance(expected, list) else [expected]
            if ticket.group_id not in values:
                return False
        elif field == "channel":
            values = expected if isinstance(expected, list) else [expected]
            if ticket.channel and ticket.channel.value not in values:
                return False
        elif field == "escalated":
            if ticket.escalated != expected:
                return False
    return True


async def _apply_actions(db: AsyncSession, ticket: Ticket, actions: list):
    """Apply trigger/scheduler/macro actions to a ticket."""
    for action in actions:
        action_type = action.get("type") or action.get("field") or action.get("action", "")
        # Normalize aliases (set_priority → priority, etc.)
        action_type = action_type.replace("set_", "")
        value = action.get("value")

        if action_type == "status":
            ticket.status = TicketStatus(value)
            if ticket.status == TicketStatus.closed:
                ticket.closed_at = datetime.now(timezone.utc)
        elif action_type == "priority":
            ticket.priority = TicketPriority(value)
        elif action_type == "assignee_id":
            ticket.assignee_id = int(value) if value else None
        elif action_type == "group_id":
            ticket.group_id = int(value) if value else None
        elif action_type == "add_tag":
            from app.models import Tag
            result = await db.execute(select(Tag).where(Tag.name == value))
            tag = result.scalar_one_or_none()
            if not tag:
                tag = Tag(name=value)
                db.add(tag)
                await db.flush()
            if tag not in ticket.tags:
                ticket.tags.append(tag)
        elif action_type == "add_note":
            article = Article(
                ticket_id=ticket.id, author_id=1,  # system
                body_html=value, is_internal=True,
                sender="system",
            )
            db.add(article)
        elif action_type == "send_email":
            # TODO: send notification email
            pass
        elif action_type == "webhook":
            webhook_id = action.get("webhook_id")
            if webhook_id:
                await fire_webhook(db, webhook_id, ticket)


async def fire_triggers(db: AsyncSession, ticket: Ticket, event: TriggerEvent):
    """Fire all matching triggers for a ticket event."""
    result = await db.execute(
        select(Trigger).where(Trigger.active == True, Trigger.event == event)
        .order_by(Trigger.position)
    )
    for trigger in result.scalars().all():
        if _match_conditions(ticket, trigger.conditions or {}):
            log.info("Trigger '%s' fired on ticket #%s", trigger.name, ticket.number)
            await _apply_actions(db, ticket, trigger.actions or [])


async def fire_webhook(db: AsyncSession, webhook_id: int, ticket: Ticket):
    """Send webhook notification."""
    webhook = await db.get(Webhook, webhook_id)
    if not webhook or not webhook.active:
        return

    payload = {
        "event": "ticket.update",
        "ticket": {
            "id": ticket.id, "number": ticket.number,
            "subject": ticket.subject, "status": ticket.status.value,
            "priority": ticket.priority.value,
            "assignee_id": ticket.assignee_id,
            "group_id": ticket.group_id,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    headers = {"Content-Type": "application/json"}
    if webhook.signature_token:
        import hmac
        import hashlib
        sig = hmac.new(
            webhook.signature_token.encode(), json.dumps(payload).encode(), hashlib.sha256
        ).hexdigest()
        headers["X-Webhook-Signature"] = sig
    headers.update(webhook.custom_headers or {})

    try:
        async with httpx.AsyncClient(verify=webhook.ssl_verify) as client:
            await client.post(webhook.endpoint, json=payload, headers=headers, timeout=10)
    except Exception:
        log.exception("Webhook '%s' failed", webhook.name)


async def run_schedulers():
    """Periodically run all active schedulers."""
    while True:
        try:
            async with async_session() as db:
                result = await db.execute(select(Scheduler).where(Scheduler.active == True))
                for scheduler in result.scalars().all():
                    now = datetime.now(timezone.utc)
                    if scheduler.last_run_at:
                        next_run = scheduler.last_run_at + timedelta(minutes=scheduler.interval_minutes)
                        if now < next_run:
                            continue

                    # Find matching tickets
                    tickets_result = await db.execute(select(Ticket))
                    for ticket in tickets_result.scalars().all():
                        if _match_conditions(ticket, scheduler.conditions or {}):
                            await _apply_actions(db, ticket, scheduler.actions or [])

                    scheduler.last_run_at = now
                await db.commit()
        except Exception:
            log.exception("Scheduler run error")

        await asyncio.sleep(60)


async def check_sla_escalations():
    """Check for SLA breaches and escalate."""
    while True:
        try:
            async with async_session() as db:
                now = datetime.now(timezone.utc)

                # Check first response escalation
                result = await db.execute(
                    select(Ticket).where(
                        Ticket.first_response_escalation_at.isnot(None),
                        Ticket.first_response_escalation_at <= now,
                        Ticket.first_response_at.is_(None),
                        Ticket.escalated == False,
                        Ticket.status.notin_([TicketStatus.closed, TicketStatus.resolved]),
                    )
                )
                for ticket in result.scalars().all():
                    ticket.escalated = True
                    log.warning("Ticket #%s escalated: first response SLA breached", ticket.number)

                    if ticket.assignee_id:
                        notif = Notification(
                            user_id=ticket.assignee_id,
                            notification_type=NotificationType.ticket_escalation,
                            ticket_id=ticket.id,
                            message=f"SLA breach: Ticket #{ticket.number} needs first response",
                        )
                        db.add(notif)

                # Check resolution escalation
                result = await db.execute(
                    select(Ticket).where(
                        Ticket.close_escalation_at.isnot(None),
                        Ticket.close_escalation_at <= now,
                        Ticket.closed_at.is_(None),
                        Ticket.status.notin_([TicketStatus.closed, TicketStatus.resolved]),
                    )
                )
                for ticket in result.scalars().all():
                    ticket.escalated = True
                    log.warning("Ticket #%s escalated: resolution SLA breached", ticket.number)

                await db.commit()
        except Exception:
            log.exception("SLA check error")

        await asyncio.sleep(60)
