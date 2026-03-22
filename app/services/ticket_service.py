from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Article, Ticket, TicketHistory, TicketStatus, Notification, NotificationType,
    Mention, User, Checklist, ChecklistItem, ChecklistTemplate,
    TicketLink, LinkType, SLA,
)


async def generate_ticket_number(db: AsyncSession) -> str:
    """Generate a unique ticket number like '20260321-0001'."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    result = await db.execute(
        select(func.count(Ticket.id)).where(Ticket.number.like(f"{today}%"))
    )
    count = result.scalar() or 0
    return f"{today}-{count + 1:04d}"


async def record_history(
    db: AsyncSession, ticket_id: int, user_id: int | None,
    action: str, field: str | None = None,
    old_value: str | None = None, new_value: str | None = None,
):
    entry = TicketHistory(
        ticket_id=ticket_id, user_id=user_id, action=action,
        field=field, old_value=old_value, new_value=new_value,
    )
    db.add(entry)


async def create_notification(
    db: AsyncSession, user_id: int, notification_type: NotificationType,
    ticket_id: int | None, message: str, article_id: int | None = None,
):
    notif = Notification(
        user_id=user_id, notification_type=notification_type,
        ticket_id=ticket_id, article_id=article_id, message=message,
    )
    db.add(notif)


async def notify_mentions(db: AsyncSession, ticket_id: int, text: str, author_id: int):
    """Find @mentions in text and create mention records + notifications."""
    if "@" not in text:
        return
    # Load all active users and match their display names in the text
    result = await db.execute(
        select(User).where(User.active == True)
    )
    all_users = result.scalars().all()
    # Sort by name length descending so longer names match first
    all_users.sort(key=lambda u: len(u.display_name), reverse=True)
    matched_users = []
    text_lower = text.lower()
    for user in all_users:
        if f"@{user.display_name.lower()}" in text_lower or f"@{user.display_name.split()[0].lower()}" in text_lower:
            matched_users.append(user)
    for user in matched_users:
        if user and user.id != author_id:
            # Upsert mention
            existing = await db.execute(
                select(Mention).where(Mention.user_id == user.id, Mention.ticket_id == ticket_id)
            )
            if not existing.scalar_one_or_none():
                db.add(Mention(user_id=user.id, ticket_id=ticket_id))
            await create_notification(
                db, user.id, NotificationType.mention, ticket_id,
                f"You were mentioned in ticket #{ticket_id}",
            )


async def merge_tickets(db: AsyncSession, source_id: int, target_id: int, user_id: int):
    """Merge source ticket into target ticket."""
    if source_id == target_id:
        return False
    source = await db.get(Ticket, source_id)
    target = await db.get(Ticket, target_id)
    if not source or not target:
        return False
    if source.status == TicketStatus.closed:
        return False
    if target.merged_into_id:
        return False  # Target is already merged elsewhere

    # Move all articles from source to target
    result = await db.execute(select(Article).where(Article.ticket_id == source_id))
    for article in result.scalars().all():
        article.ticket_id = target_id

    source.merged_into_id = target_id
    source.status = TicketStatus.closed
    source.closed_at = datetime.now(timezone.utc)

    await record_history(db, source_id, user_id, "merged", "merged_into", None, str(target_id))
    await record_history(db, target_id, user_id, "merged", "merged_from", None, str(source_id))
    return True


async def split_ticket(
    db: AsyncSession, original_ticket_id: int, article_id: int, user_id: int,
) -> Ticket | None:
    """Split an article into a new ticket."""
    article = await db.get(Article, article_id)
    if not article or article.ticket_id != original_ticket_id:
        return None

    original = await db.get(Ticket, original_ticket_id)
    number = await generate_ticket_number(db)

    new_ticket = Ticket(
        number=number,
        subject=f"Split from #{original.number}: {original.subject}",
        body_html=article.body_html,
        creator_id=article.author_id,
        group_id=original.group_id,
        organization_id=original.organization_id,
    )
    db.add(new_ticket)
    await db.flush()

    # Link tickets
    db.add(TicketLink(source_id=original_ticket_id, target_id=new_ticket.id, link_type=LinkType.related))
    await record_history(db, original_ticket_id, user_id, "split", "split_to", None, str(new_ticket.id))
    await record_history(db, new_ticket.id, user_id, "created", "split_from", None, str(original_ticket_id))

    return new_ticket


async def apply_sla(db: AsyncSession, ticket: Ticket):
    """Find and apply matching SLA to ticket."""
    result = await db.execute(
        select(SLA).where(SLA.active == True).order_by(SLA.priority.desc())
    )
    for sla in result.scalars().all():
        conditions = sla.conditions or {}
        match = True
        if "priority" in conditions and ticket.priority.value not in conditions["priority"]:
            match = False
        if "group_id" in conditions and ticket.group_id not in conditions["group_id"]:
            match = False
        if match:
            ticket.sla_id = sla.id
            now = datetime.now(timezone.utc)
            if sla.first_response_time:
                from datetime import timedelta
                ticket.first_response_escalation_at = now + timedelta(minutes=sla.first_response_time)
            if sla.solution_time:
                from datetime import timedelta
                ticket.close_escalation_at = now + timedelta(minutes=sla.solution_time)
            return


async def apply_checklist_template(db: AsyncSession, ticket_id: int, template_id: int):
    """Apply a checklist template to a ticket."""
    template = await db.get(ChecklistTemplate, template_id)
    if not template:
        return None

    checklist = Checklist(ticket_id=ticket_id)
    db.add(checklist)
    await db.flush()

    for i, item_data in enumerate(template.items or []):
        item = ChecklistItem(
            checklist_id=checklist.id,
            title=item_data.get("title", ""),
            position=i,
        )
        db.add(item)

    return checklist
