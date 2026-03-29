import enum
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey, Index, Integer,
    JSON, String, Table, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, enum.Enum):
    customer = "customer"
    agent = "agent"
    admin = "admin"


class TicketStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    pending_reminder = "pending_reminder"
    pending_close = "pending_close"
    waiting = "waiting"
    resolved = "resolved"
    closed = "closed"


class TicketPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class TicketChannel(str, enum.Enum):
    web = "web"
    email = "email"
    phone = "phone"
    chat = "chat"
    form = "form"
    api = "api"


class ArticleVisibility(str, enum.Enum):
    public = "public"
    internal = "internal"
    draft = "draft"


class LinkType(str, enum.Enum):
    parent = "parent"
    child = "child"
    related = "related"


class TriggerEvent(str, enum.Enum):
    ticket_create = "ticket.create"
    ticket_update = "ticket.update"
    article_create = "article.create"
    time_based = "time.based"


class ChecklistItemStatus(str, enum.Enum):
    open = "open"
    done = "done"


class NotificationType(str, enum.Enum):
    ticket_create = "ticket.create"
    ticket_update = "ticket.update"
    ticket_escalation = "ticket.escalation"
    mention = "mention"
    reminder = "reminder"


class TimeAccountingType(str, enum.Enum):
    billable = "billable"
    non_billable = "non_billable"
    travel = "travel"
    communication = "communication"
    other = "other"


def _utcnow():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Association Tables
# ---------------------------------------------------------------------------

user_groups = Table(
    "user_groups", Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("group_id", Integer, ForeignKey("groups.id"), primary_key=True),
)

user_organizations = Table(
    "user_organizations", Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("organization_id", Integer, ForeignKey("organizations.id"), primary_key=True),
)

ticket_tags = Table(
    "ticket_tags", Base.metadata,
    Column("ticket_id", Integer, ForeignKey("tickets.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True),
)

overview_groups = Table(
    "overview_groups", Base.metadata,
    Column("overview_id", Integer, ForeignKey("overviews.id"), primary_key=True),
    Column("group_id", Integer, ForeignKey("groups.id"), primary_key=True),
)

overview_roles = Table(
    "overview_roles", Base.metadata,
    Column("overview_id", Integer, ForeignKey("overviews.id"), primary_key=True),
    Column("role", Enum(UserRole)),
)


# ---------------------------------------------------------------------------
# Core Models
# ---------------------------------------------------------------------------

class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    display_name = Column(String(255), nullable=False)
    active = Column(Boolean, default=True)
    note = Column(Text, default="")
    signature_id = Column(Integer, ForeignKey("signatures.id"), nullable=True)
    email_address = Column(String(320), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    users = relationship("User", secondary=user_groups, back_populates="groups")
    tickets = relationship("Ticket", back_populates="group")
    signature = relationship("Signature", back_populates="groups")


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    domain = Column(String(255), nullable=True)
    domain_assignment = Column(Boolean, default=False)
    shared = Column(Boolean, default=True)
    vip = Column(Boolean, default=False)
    active = Column(Boolean, default=True)
    note = Column(Text, default="")
    custom_fields = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    members = relationship("User", secondary=user_organizations, back_populates="organizations")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    entra_oid = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(320), unique=True, nullable=False)
    display_name = Column(String(255), nullable=False)
    firstname = Column(String(255), default="")
    lastname = Column(String(255), default="")
    phone = Column(String(100), nullable=True)
    mobile = Column(String(100), nullable=True)
    role = Column(Enum(UserRole), default=UserRole.customer, nullable=False)
    active = Column(Boolean, default=True)
    vip = Column(Boolean, default=False)
    verified = Column(Boolean, default=False)
    locale = Column(String(10), default="en")
    timezone = Column(String(64), default="UTC")
    note = Column(Text, default="")
    custom_fields = Column(JSON, default=dict)

    # Out of office
    out_of_office = Column(Boolean, default=False)
    out_of_office_start = Column(DateTime(timezone=True), nullable=True)
    out_of_office_end = Column(DateTime(timezone=True), nullable=True)
    out_of_office_replacement_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Organization
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)

    # 2FA
    totp_secret = Column(String(255), nullable=True)
    two_factor_enabled = Column(Boolean, default=False)

    # API
    api_token = Column(String(255), nullable=True, unique=True)
    api_token_last_used = Column(DateTime(timezone=True), nullable=True)

    # Password (for local auth fallback)
    password_hash = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    last_login = Column(DateTime(timezone=True), nullable=True)

    organization = relationship("Organization", foreign_keys=[organization_id])
    organizations = relationship("Organization", secondary=user_organizations, back_populates="members")
    groups = relationship("Group", secondary=user_groups, back_populates="users")
    replacement = relationship("User", remote_side="User.id", foreign_keys=[out_of_office_replacement_id])

    created_tickets = relationship("Ticket", back_populates="creator", foreign_keys="Ticket.creator_id")
    assigned_tickets = relationship("Ticket", back_populates="assignee", foreign_keys="Ticket.assignee_id")
    mentions = relationship("Mention", back_populates="user")
    notifications = relationship("Notification", back_populates="user", order_by="Notification.created_at.desc()")


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        Index("ix_tickets_status", "status"),
        Index("ix_tickets_assignee", "assignee_id"),
        Index("ix_tickets_group", "group_id"),
        Index("ix_tickets_org", "organization_id"),
    )

    id = Column(Integer, primary_key=True)
    number = Column(String(20), unique=True, nullable=False)
    subject = Column(String(500), nullable=False)
    body_html = Column(Text, nullable=False, default="")
    status = Column(Enum(TicketStatus), default=TicketStatus.open, nullable=False)
    priority = Column(Enum(TicketPriority), default=TicketPriority.medium, nullable=False)
    channel = Column(Enum(TicketChannel), default=TicketChannel.web, nullable=False)

    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)

    # Pending
    pending_time = Column(DateTime(timezone=True), nullable=True)

    # Merge
    merged_into_id = Column(Integer, ForeignKey("tickets.id"), nullable=True)

    # SLA
    sla_id = Column(Integer, ForeignKey("slas.id"), nullable=True)
    first_response_at = Column(DateTime(timezone=True), nullable=True)
    first_response_escalation_at = Column(DateTime(timezone=True), nullable=True)
    close_escalation_at = Column(DateTime(timezone=True), nullable=True)
    escalated = Column(Boolean, default=False)

    # Custom fields
    custom_fields = Column(JSON, default=dict)

    # Email threading
    email_message_id = Column(String(500), nullable=True, index=True)

    # Time accounting
    time_spent = Column(Float, default=0.0)

    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    group = relationship("Group", back_populates="tickets")
    creator = relationship("User", back_populates="created_tickets", foreign_keys=[creator_id])
    assignee = relationship("User", back_populates="assigned_tickets", foreign_keys=[assignee_id])
    organization = relationship("Organization")
    merged_into = relationship("Ticket", remote_side="Ticket.id", foreign_keys=[merged_into_id])
    sla = relationship("SLA")

    articles = relationship("Article", back_populates="ticket", order_by="Article.created_at")
    tags = relationship("Tag", secondary=ticket_tags, back_populates="tickets")
    links_from = relationship("TicketLink", foreign_keys="TicketLink.source_id", back_populates="source")
    links_to = relationship("TicketLink", foreign_keys="TicketLink.target_id", back_populates="target")
    history = relationship("TicketHistory", back_populates="ticket", order_by="TicketHistory.created_at")
    checklist = relationship("Checklist", back_populates="ticket", uselist=False)
    mentions = relationship("Mention", back_populates="ticket")
    time_entries = relationship("TimeEntry", back_populates="ticket")
    attachments = relationship("Attachment", back_populates="ticket")

    # Keep backward compat alias
    @property
    def comments(self):
        return self.articles


class Article(Base):
    """Article model for ticket communication entries."""
    __tablename__ = "articles"
    __table_args__ = (Index("ix_articles_ticket", "ticket_id"),)

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    body_html = Column(Text, nullable=False)
    body_text = Column(Text, default="")
    content_type = Column(String(50), default="text/html")
    is_internal = Column(Boolean, default=False)
    channel = Column(Enum(TicketChannel), default=TicketChannel.web)
    sender = Column(String(50), default="agent")  # agent, customer, system

    # Email fields
    email_message_id = Column(String(500), nullable=True, index=True)
    email_from = Column(String(500), nullable=True)
    email_to = Column(String(1000), nullable=True)
    email_cc = Column(String(1000), nullable=True)
    email_subject = Column(String(500), nullable=True)
    email_in_reply_to = Column(String(500), nullable=True)
    email_references = Column(Text, nullable=True)
    email_delivery_status = Column(String(50), nullable=True)  # sent, failed, pending

    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    ticket = relationship("Ticket", back_populates="articles")
    author = relationship("User")
    attachments = relationship("ArticleAttachment", back_populates="article")


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------

class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    filename = Column(String(500), nullable=False)
    content_type = Column(String(255), default="application/octet-stream")
    size = Column(Integer, default=0)
    stored_path = Column(String(1000), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    ticket = relationship("Ticket", back_populates="attachments")


class ArticleAttachment(Base):
    __tablename__ = "article_attachments"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    filename = Column(String(500), nullable=False)
    content_type = Column(String(255), default="application/octet-stream")
    size = Column(Integer, default=0)
    stored_path = Column(String(1000), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    article = relationship("Article", back_populates="attachments")


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    tickets = relationship("Ticket", secondary=ticket_tags, back_populates="tags")


# ---------------------------------------------------------------------------
# Ticket Links
# ---------------------------------------------------------------------------

class TicketLink(Base):
    __tablename__ = "ticket_links"
    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "link_type"),
    )

    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    target_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    link_type = Column(Enum(LinkType), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    source = relationship("Ticket", foreign_keys=[source_id], back_populates="links_from")
    target = relationship("Ticket", foreign_keys=[target_id], back_populates="links_to")


# ---------------------------------------------------------------------------
# Ticket History (Audit Trail)
# ---------------------------------------------------------------------------

class TicketHistory(Base):
    __tablename__ = "ticket_history"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(50), nullable=False)  # created, updated, merged, split, etc.
    field = Column(String(100), nullable=True)  # which field changed
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    ticket = relationship("Ticket", back_populates="history")
    user = relationship("User")


# ---------------------------------------------------------------------------
# Checklists
# ---------------------------------------------------------------------------

class ChecklistTemplate(Base):
    __tablename__ = "checklist_templates"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    items = Column(JSON, default=list)  # list of {title: str}
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class Checklist(Base):
    __tablename__ = "checklists"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    ticket = relationship("Ticket", back_populates="checklist")
    items = relationship("ChecklistItem", back_populates="checklist", order_by="ChecklistItem.position")


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id = Column(Integer, primary_key=True)
    checklist_id = Column(Integer, ForeignKey("checklists.id"), nullable=False)
    title = Column(String(500), nullable=False)
    status = Column(Enum(ChecklistItemStatus), default=ChecklistItemStatus.open)
    position = Column(Integer, default=0)
    ticket_link_id = Column(Integer, ForeignKey("tickets.id"), nullable=True)  # link item to ticket
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    checklist = relationship("Checklist", back_populates="items")
    linked_ticket = relationship("Ticket")


# ---------------------------------------------------------------------------
# SLAs
# ---------------------------------------------------------------------------

class SLA(Base):
    __tablename__ = "slas"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    first_response_time = Column(Integer, nullable=True)  # minutes
    update_time = Column(Integer, nullable=True)  # minutes
    solution_time = Column(Integer, nullable=True)  # minutes
    calendar_id = Column(Integer, ForeignKey("calendars.id"), nullable=True)
    conditions = Column(JSON, default=dict)  # matching conditions
    active = Column(Boolean, default=True)
    priority = Column(Integer, default=0)  # higher = checked first
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    calendar = relationship("Calendar")


# ---------------------------------------------------------------------------
# Business Calendars
# ---------------------------------------------------------------------------

class Calendar(Base):
    __tablename__ = "calendars"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    timezone = Column(String(64), default="UTC")
    business_hours = Column(JSON, default=dict)  # {mon: {start: "09:00", end: "17:00"}, ...}
    holidays = Column(JSON, default=list)  # [{date: "2026-01-01", name: "New Year"}]
    is_default = Column(Boolean, default=False)
    active = Column(Boolean, default=True)
    ical_url = Column(String(1000), nullable=True)  # optional iCal feed URL for holidays
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# Automation: Triggers
# ---------------------------------------------------------------------------

class Trigger(Base):
    __tablename__ = "triggers"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    event = Column(Enum(TriggerEvent), nullable=False)
    conditions = Column(JSON, default=dict)  # conditions to match
    actions = Column(JSON, default=list)  # actions to perform
    active = Column(Boolean, default=True)
    position = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# Automation: Schedulers
# ---------------------------------------------------------------------------

class Scheduler(Base):
    __tablename__ = "schedulers"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    conditions = Column(JSON, default=dict)  # ticket matching conditions
    actions = Column(JSON, default=list)  # actions to perform
    interval_minutes = Column(Integer, default=60)
    active = Column(Boolean, default=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# Automation: Macros
# ---------------------------------------------------------------------------

class Macro(Base):
    __tablename__ = "macros"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    actions = Column(JSON, default=list)  # [{field: "status", value: "closed"}, ...]
    active = Column(Boolean, default=True)
    group_ids = Column(JSON, default=list)  # restrict to groups, empty = all
    note = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

class Webhook(Base):
    __tablename__ = "webhooks"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    endpoint = Column(String(1000), nullable=False)
    signature_token = Column(String(255), nullable=True)
    ssl_verify = Column(Boolean, default=True)
    active = Column(Boolean, default=True)
    note = Column(Text, default="")
    custom_headers = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# Text Modules (:: snippets)
# ---------------------------------------------------------------------------

class TextModule(Base):
    __tablename__ = "text_modules"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    keyword = Column(String(100), nullable=False, index=True)  # shortcut trigger
    content = Column(Text, nullable=False)
    active = Column(Boolean, default=True)
    group_ids = Column(JSON, default=list)  # restrict to groups
    note = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# Ticket Templates
# ---------------------------------------------------------------------------

class TicketTemplate(Base):
    __tablename__ = "ticket_templates"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    subject = Column(String(500), default="")
    body = Column(Text, default="")
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    priority = Column(Enum(TicketPriority), nullable=True)
    tags = Column(JSON, default=list)
    custom_fields = Column(JSON, default=dict)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# Signatures
# ---------------------------------------------------------------------------

class Signature(Base):
    __tablename__ = "signatures"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    body_html = Column(Text, default="")
    active = Column(Boolean, default=True)
    note = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    groups = relationship("Group", back_populates="signature")


# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------

class KBCategory(Base):
    __tablename__ = "kb_categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    parent_id = Column(Integer, ForeignKey("kb_categories.id"), nullable=True)
    position = Column(Integer, default=0)
    icon = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    parent = relationship("KBCategory", remote_side="KBCategory.id", backref="children")
    articles = relationship("KBArticle", back_populates="category")


class KBArticle(Base):
    __tablename__ = "kb_articles"

    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("kb_categories.id"), nullable=False)
    title = Column(String(500), nullable=False)
    body_html = Column(Text, nullable=False, default="")
    locale = Column(String(10), default="en")
    visibility = Column(Enum(ArticleVisibility), default=ArticleVisibility.draft)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    position = Column(Integer, default=0)
    tags = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    category = relationship("KBCategory", back_populates="articles")
    author = relationship("User")


# ---------------------------------------------------------------------------
# Overviews (customizable ticket lists)
# ---------------------------------------------------------------------------

class Overview(Base):
    __tablename__ = "overviews"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    link = Column(String(255), nullable=True)  # URL slug
    conditions = Column(JSON, default=dict)  # filter conditions
    order_by = Column(String(100), default="created_at")
    order_direction = Column(String(4), default="desc")
    columns = Column(JSON, default=list)  # visible columns
    per_page = Column(Integer, default=25)
    active = Column(Boolean, default=True)
    position = Column(Integer, default=0)
    # Access control
    roles = Column(JSON, default=list)  # which roles can see this
    group_ids = Column(JSON, default=list)  # which groups can see this
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# Mentions
# ---------------------------------------------------------------------------

class Mention(Base):
    __tablename__ = "mentions"
    __table_args__ = (
        UniqueConstraint("user_id", "ticket_id"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    user = relationship("User", back_populates="mentions")
    ticket = relationship("Ticket", back_populates="mentions")


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    notification_type = Column(Enum(NotificationType), nullable=False)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=True)
    message = Column(Text, nullable=False)
    seen = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    user = relationship("User", back_populates="notifications")
    ticket = relationship("Ticket")
    article = relationship("Article")


# ---------------------------------------------------------------------------
# Notification Preferences
# ---------------------------------------------------------------------------

class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    ticket_create = Column(Boolean, default=True)
    ticket_update = Column(Boolean, default=True)
    ticket_escalation = Column(Boolean, default=True)
    mention = Column(Boolean, default=True)
    reminder = Column(Boolean, default=True)
    email_enabled = Column(Boolean, default=True)
    desktop_enabled = Column(Boolean, default=True)

    user = relationship("User")


# ---------------------------------------------------------------------------
# Time Accounting
# ---------------------------------------------------------------------------

class TimeEntry(Base):
    __tablename__ = "time_entries"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    time_minutes = Column(Float, nullable=False)
    activity_type = Column(Enum(TimeAccountingType), default=TimeAccountingType.other)
    note = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    ticket = relationship("Ticket", back_populates="time_entries")
    user = relationship("User")


# ---------------------------------------------------------------------------
# Email Accounts
# ---------------------------------------------------------------------------

class EmailAccount(Base):
    __tablename__ = "email_accounts"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email_address = Column(String(320), nullable=False)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    auth_type = Column(String(20), default="basic")  # "basic" or "oauth2"

    # Inbound
    imap_host = Column(String(255), nullable=True)
    imap_port = Column(Integer, default=993)
    imap_user = Column(String(320), nullable=True)
    imap_password = Column(String(500), nullable=True)
    imap_ssl = Column(Boolean, default=True)
    imap_folder = Column(String(255), default="INBOX")

    # Outbound
    smtp_host = Column(String(255), nullable=True)
    smtp_port = Column(Integer, default=587)
    smtp_user = Column(String(320), nullable=True)
    smtp_password = Column(String(500), nullable=True)

    active = Column(Boolean, default=True)
    last_poll_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    group = relationship("Group", foreign_keys=[group_id])


# ---------------------------------------------------------------------------
# Core Workflows (dynamic forms)
# ---------------------------------------------------------------------------

class CoreWorkflow(Base):
    __tablename__ = "core_workflows"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    object_type = Column(String(50), default="ticket")  # ticket, user, org
    conditions = Column(JSON, default=dict)  # when to apply
    actions = Column(JSON, default=list)  # show/hide/required/readonly fields
    active = Column(Boolean, default=True)
    position = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# Custom Object Attributes
# ---------------------------------------------------------------------------

class ObjectAttribute(Base):
    __tablename__ = "object_attributes"

    id = Column(Integer, primary_key=True)
    object_type = Column(String(50), nullable=False)  # ticket, user, organization
    name = Column(String(100), nullable=False)
    display_name = Column(String(255), nullable=False)
    data_type = Column(String(50), nullable=False)  # input, select, boolean, date, datetime, integer, textarea
    data_options = Column(JSON, default=dict)  # {options: [...], default: ..., min: ..., max: ...}
    position = Column(Integer, default=0)
    active = Column(Boolean, default=True)
    required = Column(Boolean, default=False)
    editable = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (UniqueConstraint("object_type", "name"),)


# ---------------------------------------------------------------------------
# Branding / Settings
# ---------------------------------------------------------------------------

class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(255), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# Session / Device Log
# ---------------------------------------------------------------------------

class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String(255), unique=True, nullable=False)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    last_seen_at = Column(DateTime(timezone=True), default=_utcnow)

    user = relationship("User")


class UserDevice(Base):
    __tablename__ = "user_devices"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    os = Column(String(100), nullable=True)
    browser = Column(String(100), nullable=True)
    ip_address = Column(String(45), nullable=True)
    fingerprint = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    last_seen_at = Column(DateTime(timezone=True), default=_utcnow)

    user = relationship("User")


# ---------------------------------------------------------------------------
# GDPR / Data Privacy
# ---------------------------------------------------------------------------

class DataPrivacyTask(Base):
    __tablename__ = "data_privacy_tasks"

    id = Column(Integer, primary_key=True)
    deletable_type = Column(String(50), nullable=False)  # user, organization
    deletable_id = Column(Integer, nullable=False)
    state = Column(String(50), default="pending")  # pending, in_progress, completed, failed
    requested_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    requested_by = relationship("User")


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    agent_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=True)
    state = Column(String(50), default="waiting")  # waiting, active, closed
    visitor_name = Column(String(255), nullable=True)
    visitor_email = Column(String(320), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    customer = relationship("User", foreign_keys=[customer_id])
    agent = relationship("User", foreign_keys=[agent_id])
    ticket = relationship("Ticket")
    messages = relationship("ChatMessage", back_populates="session", order_by="ChatMessage.created_at")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    body = Column(Text, nullable=False)
    sender_type = Column(String(20), default="customer")  # customer, agent, system
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    session = relationship("ChatSession", back_populates="messages")
    sender = relationship("User")


# ---------------------------------------------------------------------------
# Web Form
# ---------------------------------------------------------------------------

class WebForm(Base):
    __tablename__ = "web_forms"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    title = Column(String(255), default="Contact Us")
    success_message = Column(Text, default="Thank you! Your request has been submitted.")
    fields = Column(JSON, default=list)  # [{name, label, type, required}]
    active = Column(Boolean, default=True)
    embed_code = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
