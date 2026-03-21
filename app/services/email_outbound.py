import logging
from email.message import EmailMessage
from aiosmtplib import send as smtp_send
from app.config import settings
from app.models import Article, Ticket, User

log = logging.getLogger(__name__)


def _make_message_id(ticket_id: int, article_id: int | None = None) -> str:
    if article_id:
        return f"<ticket-{ticket_id}-article-{article_id}@deskflow>"
    return f"<ticket-{ticket_id}@deskflow>"


async def _send(msg: EmailMessage):
    if not settings.SMTP_HOST or not settings.SMTP_USER:
        log.debug("SMTP not configured, skipping email send")
        return
    try:
        await smtp_send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            start_tls=True,
        )
    except Exception:
        log.exception("Failed to send email")


async def send_ticket_notification(ticket: Ticket, creator: User):
    msg = EmailMessage()
    msg["Subject"] = f"[DeskFlow #{ticket.number}] {ticket.subject}"
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


async def send_comment_notification(ticket: Ticket, article: Article, author: User):
    msg = EmailMessage()
    msg["Subject"] = f"Re: [DeskFlow #{ticket.number}] {ticket.subject}"
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM}>"
    msg["To"] = settings.SMTP_FROM
    msg["Message-ID"] = _make_message_id(ticket.id, article.id)
    msg["In-Reply-To"] = _make_message_id(ticket.id)
    msg["References"] = _make_message_id(ticket.id)
    msg["Reply-To"] = settings.SMTP_FROM
    msg.set_content(
        f"New reply on ticket #{ticket.number} by {author.display_name}:\n\n"
        f"{article.body_html}"
    )
    article.email_message_id = _make_message_id(ticket.id, article.id)
    await _send(msg)
