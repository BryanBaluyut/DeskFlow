"""Pydantic validation schemas for request data."""
from pydantic import BaseModel, Field, field_validator
import bleach

ALLOWED_TAGS = [
    "p", "br", "b", "i", "u", "a", "ul", "ol", "li", "pre", "code",
    "strong", "em", "blockquote", "h1", "h2", "h3", "h4", "img",
    "table", "thead", "tbody", "tr", "th", "td",
]
ALLOWED_ATTRS = {"a": ["href", "title"], "img": ["src", "alt", "width", "height"]}


def sanitize_html(value: str) -> str:
    return bleach.clean(value, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)


# --- Tickets ---

class TicketCreateForm(BaseModel):
    subject: str = Field(..., min_length=1, max_length=500)
    body: str = ""
    priority: str = "medium"
    group_id: int | None = None
    tags: str = ""

    @field_validator("subject")
    @classmethod
    def strip_subject(cls, v: str) -> str:
        return v.strip()

    @field_validator("body")
    @classmethod
    def sanitize_body(cls, v: str) -> str:
        return sanitize_html(v)

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        if v not in ("low", "medium", "high", "critical"):
            raise ValueError("Invalid priority")
        return v


class TicketUpdateForm(BaseModel):
    status: str | None = None
    priority: str | None = None
    assignee_id: str | None = None
    group_id: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None:
            valid = ("open", "in_progress", "pending_reminder", "pending_close",
                     "waiting", "resolved", "closed")
            if v not in valid:
                raise ValueError("Invalid status")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str | None) -> str | None:
        if v is not None and v not in ("low", "medium", "high", "critical"):
            raise ValueError("Invalid priority")
        return v


class ArticleCreateForm(BaseModel):
    body: str = Field(..., min_length=1)
    is_internal: bool = False

    @field_validator("body")
    @classmethod
    def sanitize_body(cls, v: str) -> str:
        return sanitize_html(v)


class BulkActionForm(BaseModel):
    ticket_ids: str
    action: str
    value: str = ""

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in ("status", "priority", "assignee_id", "group_id", "close"):
            raise ValueError("Invalid bulk action")
        return v


# --- Admin ---

class GroupCreateForm(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    display_name: str = ""
    email_address: str = ""
    signature_id: int | None = None


class OrganizationCreateForm(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    domain: str = ""
    domain_assignment: bool = False
    shared: bool = True
    note: str = ""


class SLACreateForm(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    first_response_time: int | None = None
    update_time: int | None = None
    solution_time: int | None = None
    calendar_id: int | None = None

    @field_validator("first_response_time", "update_time", "solution_time")
    @classmethod
    def validate_positive(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("Time values must be positive")
        return v


class TriggerCreateForm(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    event: str
    conditions: str = "{}"
    actions: str = "[]"

    @field_validator("event")
    @classmethod
    def validate_event(cls, v: str) -> str:
        valid = ("ticket.create", "ticket.update", "article.create", "time.based")
        if v not in valid:
            raise ValueError("Invalid trigger event")
        return v


class MacroCreateForm(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    actions: str = "[]"
    note: str = ""


class WebhookCreateForm(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    endpoint: str = Field(..., min_length=1, max_length=1000)
    signature_token: str = ""


class TextModuleCreateForm(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    keyword: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1)


class BrandingForm(BaseModel):
    product_name: str = "DeskFlow"
    primary_color: str = "#2563eb"
    custom_css: str = ""

    @field_validator("primary_color")
    @classmethod
    def validate_color(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("#") or len(v) not in (4, 7):
            raise ValueError("Invalid hex color")
        return v


# --- Portal ---

class PortalTicketCreateForm(BaseModel):
    subject: str = Field(..., min_length=1, max_length=500)
    body: str = ""
    priority: str = "medium"

    @field_validator("subject")
    @classmethod
    def strip_subject(cls, v: str) -> str:
        return v.strip()

    @field_validator("body")
    @classmethod
    def sanitize_body(cls, v: str) -> str:
        return sanitize_html(v)


class PortalReplyForm(BaseModel):
    body: str = Field(..., min_length=1)

    @field_validator("body")
    @classmethod
    def sanitize_body(cls, v: str) -> str:
        return sanitize_html(v)


class ProfileUpdateForm(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=255)
    phone: str = ""
    locale: str = "en"
    timezone: str = "UTC"


# --- Knowledge Base ---

class KBArticleForm(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    body_html: str = ""
    category_id: int
    visibility: str = "draft"

    @field_validator("body_html")
    @classmethod
    def sanitize_body(cls, v: str) -> str:
        return sanitize_html(v)

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        if v not in ("public", "internal", "draft"):
            raise ValueError("Invalid visibility")
        return v


class KBCategoryForm(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    parent_id: int | None = None
