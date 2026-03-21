import asyncio
import email
import logging
import re
from email import policy

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models import (
    Article, EmailAccount, Ticket, TicketChannel, TicketStatus, User, UserRole,
)
from app.services.ticket_service import generate_ticket_number

log = logging.getLogger(__name__)

TICKET_RE = re.compile(r"\[DeskFlow #(\w+-\d+|\d+)\]")


async def _get_or_create_email_user(db: AsyncSession, from_addr: str, from_name: str) -> User:
    result = await db.execute(select(User).where(User.email == from_addr))
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            entra_oid=f"email-{from_addr}",
            email=from_addr,
            display_name=from_name or from_addr,
            role=UserRole.customer,
        )
        db.add(user)
        await db.flush()
    return user


def _extract_body(msg: email.message.EmailMessage) -> str:
    body = msg.get_body(preferencelist=("plain",))
    if body:
        content = body.get_content()
        lines = content.split("\n")
        cleaned = []
        for line in lines:
            if line.startswith(">") or (line.startswith("On ") and "wrote:" in line):
                break
            cleaned.append(line)
        return "\n".join(cleaned).strip()
    return ""


async def process_message(raw_bytes: bytes, group_id: int | None = None):
    msg = email.message_from_bytes(raw_bytes, policy=policy.default)

    from_header = msg.get("From", "")
    from_name = ""
    from_addr = from_header
    if "<" in from_header:
        from_name = from_header.split("<")[0].strip().strip('"')
        from_addr = from_header.split("<")[1].rstrip(">").strip()

    subject = msg.get("Subject", "No Subject")
    body = _extract_body(msg)
    message_id = msg.get("Message-ID", "")
    in_reply_to = msg.get("In-Reply-To", "")

    async with async_session() as db:
        user = await _get_or_create_email_user(db, from_addr, from_name)

        # Check if this is a reply to an existing ticket
        ticket_id = None
        match = TICKET_RE.search(subject)
        if match:
            ticket_ref = match.group(1)
            # Try by number first
            result = await db.execute(select(Ticket).where(Ticket.number == ticket_ref))
            existing = result.scalar_one_or_none()
            if existing:
                ticket_id = existing.id
            elif ticket_ref.isdigit():
                ticket_id = int(ticket_ref)

        if not ticket_id and in_reply_to:
            result = await db.execute(
                select(Ticket).where(Ticket.email_message_id == in_reply_to)
            )
            existing = result.scalar_one_or_none()
            if existing:
                ticket_id = existing.id

        if ticket_id:
            ticket = await db.get(Ticket, ticket_id)
            if ticket:
                article = Article(
                    ticket_id=ticket.id,
                    author_id=user.id,
                    body_html=body,
                    email_message_id=message_id,
                    channel=TicketChannel.email,
                    sender="customer",
                    email_from=from_addr,
                    email_subject=subject,
                    email_in_reply_to=in_reply_to,
                )
                db.add(article)
                if ticket.status in (TicketStatus.resolved, TicketStatus.pending_close):
                    ticket.status = TicketStatus.open
                await db.commit()
                log.info("Added email article to ticket #%s", ticket.number)
                return

        # Create new ticket
        number = await generate_ticket_number(db)
        ticket = Ticket(
            number=number,
            subject=subject,
            body_html=body,
            creator_id=user.id,
            email_message_id=message_id,
            channel=TicketChannel.email,
            group_id=group_id,
        )
        db.add(ticket)
        await db.flush()

        article = Article(
            ticket_id=ticket.id,
            author_id=user.id,
            body_html=body,
            email_message_id=message_id,
            channel=TicketChannel.email,
            sender="customer",
            email_from=from_addr,
            email_subject=subject,
        )
        db.add(article)
        await db.commit()
        log.info("Created ticket #%s from email", ticket.number)


async def poll_imap():
    """Poll all configured email accounts, plus the global IMAP config."""
    while True:
        try:
            # Poll globally configured account
            if settings.IMAP_HOST and settings.IMAP_USER:
                await _poll_account(
                    settings.IMAP_HOST, settings.IMAP_PORT,
                    settings.IMAP_USER, settings.IMAP_PASSWORD,
                    group_id=None,
                )

            # Poll per-account email accounts from DB
            async with async_session() as db:
                result = await db.execute(
                    select(EmailAccount).where(
                        EmailAccount.active == True,
                        EmailAccount.imap_host.isnot(None),
                    )
                )
                for account in result.scalars().all():
                    await _poll_account(
                        account.imap_host, account.imap_port,
                        account.imap_user, account.imap_password,
                        group_id=account.group_id,
                    )
                    account.last_poll_at = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
                await db.commit()

        except Exception:
            log.exception("IMAP polling error")

        await asyncio.sleep(settings.EMAIL_POLL_INTERVAL)


async def _poll_account(host: str, port: int, user: str, password: str, group_id: int | None):
    if not host or not user:
        return
    try:
        import aioimaplib
        client = aioimaplib.IMAP4_SSL(host=host, port=port)
        await client.wait_hello_from_server()
        await client.login(user, password)
        await client.select("INBOX")

        _, data = await client.search("UNSEEN")
        if data and data[0]:
            msg_nums = data[0].split()
            for num in msg_nums:
                _, msg_data = await client.fetch(num.decode(), "(RFC822)")
                if msg_data:
                    for item in msg_data:
                        if isinstance(item, tuple) and len(item) == 2:
                            await process_message(item[1], group_id=group_id)
                    await client.store(num.decode(), "+FLAGS", "\\Seen")

        await client.logout()
    except Exception:
        log.exception("IMAP poll error for %s@%s", user, host)
