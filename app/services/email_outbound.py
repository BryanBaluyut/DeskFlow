import logging
from email.message import EmailMessage

import aiosmtplib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Article, EmailAccount, NotificationPreference, Ticket, User

log = logging.getLogger(__name__)


def _make_message_id(ticket_id: int, article_id: int | None = None) -> str:
    if article_id:
        return f"<ticket-{ticket_id}-article-{article_id}@slatedesk>"
    return f"<ticket-{ticket_id}@slatedesk>"


async def _send(
    msg: EmailMessage,
    smtp_config: dict | None = None,
):
    """Send an email via SMTP, supporting both basic and OAuth2 auth.

    smtp_config can override: host, port, user, password, email_address, auth_type.
    Defaults to global settings.
    """
    cfg = smtp_config or {}
    host = cfg.get("host") or settings.SMTP_HOST
    port = cfg.get("port") or settings.SMTP_PORT
    user = cfg.get("user") or settings.SMTP_USER
    password = cfg.get("password") or settings.SMTP_PASSWORD
    email_address = cfg.get("email_address") or user
    auth_type = cfg.get("auth_type") or settings.EMAIL_AUTH_TYPE

    if not host or not (user or email_address):
        log.debug("SMTP not configured, skipping email send")
        return

    try:
        if auth_type == "oauth2":
            from app.services.email_oauth import get_oauth2_token
            token = await get_oauth2_token(email_address)
            client = aiosmtplib.SMTP(hostname=host, port=port, start_tls=True)
            await client.connect()
            await client.ehlo()
            await client.auth_xoauth2(email_address, token)
            await client.send_message(msg)
            await client.quit()
        else:
            await aiosmtplib.send(
                msg,
                hostname=host,
                port=port,
                username=user,
                password=password,
                start_tls=True,
            )
    except Exception:
        log.exception("Failed to send email")


async def send_ticket_notification(ticket: Ticket, creator: User):
    msg = EmailMessage()
    msg["Subject"] = f"[SlateDesk #{ticket.number}] {ticket.subject}"
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM}>"
    msg["To"] = creator.email
    msg["Message-ID"] = _make_message_id(ticket.id)
    msg["Reply-To"] = settings.SMTP_FROM
    msg.set_content(
        f"Your ticket #{ticket.number} has been created.\n\n"
        f"Subject: {ticket.subject}\n\n"
        f"You can reply to this email to add comments."
    )
    msg.add_alternative(
        f"<p>Your ticket <strong>#{ticket.number}</strong> has been created.</p>"
        f"<p>Subject: {ticket.subject}</p>"
        f"<p>You can reply to this email to add comments.</p>",
        subtype="html",
    )
    ticket.email_message_id = _make_message_id(ticket.id)
    await _send(msg)


async def send_comment_notification(
    ticket: Ticket, article: Article, author: User,
    db: AsyncSession | None = None,
):
    """Notify the other party when a comment is added.

    If the author is an agent, email the ticket creator (customer).
    If the author is a customer, email the assigned agent.
    """
    if article.sender == "agent":
        await _send_customer_notification(ticket, article, author)
    elif article.sender == "customer" and ticket.assignee_id and db:
        assignee = await db.get(User, ticket.assignee_id)
        if assignee:
            await _send_agent_notification(ticket, article, author, assignee)


async def _check_email_preference(user_id: int) -> bool:
    """Check if a user has email notifications enabled. Defaults to True."""
    from app.database import async_session
    async with async_session() as db:
        result = await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id
            )
        )
        pref = result.scalar_one_or_none()
        if pref is None:
            return True
        return pref.email_enabled


async def _send_customer_notification(
    ticket: Ticket, article: Article, author: User,
):
    """Email the ticket creator when an agent comments."""
    creator = ticket.creator
    if not creator or not creator.email:
        return
    if not await _check_email_preference(creator.id):
        return
    msg = EmailMessage()
    msg["Subject"] = f"Re: [SlateDesk #{ticket.number}] {ticket.subject}"
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM}>"
    msg["To"] = creator.email
    msg["Message-ID"] = _make_message_id(ticket.id, article.id)
    msg["In-Reply-To"] = ticket.email_message_id or _make_message_id(ticket.id)
    msg["References"] = ticket.email_message_id or _make_message_id(ticket.id)
    msg["Reply-To"] = settings.SMTP_FROM
    msg.set_content(
        f"New reply on ticket #{ticket.number} by {author.display_name}:\n\n"
        f"{article.body_html}"
    )
    msg.add_alternative(
        f"<p>New reply on ticket <strong>#{ticket.number}</strong> "
        f"by {author.display_name}:</p>{article.body_html}",
        subtype="html",
    )
    article.email_message_id = _make_message_id(ticket.id, article.id)
    smtp_config = await resolve_smtp_config(ticket) if ticket.group_id else None
    await _send(msg, smtp_config=smtp_config)


async def _send_agent_notification(
    ticket: Ticket, article: Article, customer: User, agent: User,
):
    """Email the assigned agent when a customer comments."""
    if not agent.email:
        return
    if not await _check_email_preference(agent.id):
        return
    msg = EmailMessage()
    msg["Subject"] = f"Re: [SlateDesk #{ticket.number}] {ticket.subject}"
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM}>"
    msg["To"] = agent.email
    msg["Message-ID"] = _make_message_id(ticket.id, article.id)
    msg["In-Reply-To"] = ticket.email_message_id or _make_message_id(ticket.id)
    msg["References"] = ticket.email_message_id or _make_message_id(ticket.id)
    msg["Reply-To"] = settings.SMTP_FROM
    msg.set_content(
        f"Customer {customer.display_name} replied on ticket #{ticket.number}:\n\n"
        f"{article.body_html}"
    )
    msg.add_alternative(
        f"<p>Customer <strong>{customer.display_name}</strong> replied on "
        f"ticket <strong>#{ticket.number}</strong>:</p>{article.body_html}",
        subtype="html",
    )
    article.email_message_id = _make_message_id(ticket.id, article.id)
    smtp_config = await resolve_smtp_config(ticket) if ticket.group_id else None
    await _send(msg, smtp_config=smtp_config)


async def resolve_smtp_config(ticket: Ticket) -> dict | None:
    """Resolve per-account SMTP config for a ticket's group, if available."""
    if not ticket.group_id:
        return None
    from app.database import async_session
    async with async_session() as db:
        result = await db.execute(
            select(EmailAccount).where(
                EmailAccount.group_id == ticket.group_id,
                EmailAccount.active == True,  # noqa: E712
                EmailAccount.smtp_host.isnot(None),
            ).limit(1)
        )
        account = result.scalar_one_or_none()
        if not account:
            return None
        return {
            "host": account.smtp_host,
            "port": account.smtp_port,
            "user": account.smtp_user,
            "password": account.smtp_password,
            "email_address": account.email_address,
            "auth_type": getattr(account, "auth_type", "basic"),
        }
