# SlateDesk - IT Help Desk Ticketing System

A comprehensive, Docker-deployable IT help desk ticketing system with enterprise-grade features, Microsoft Entra ID SSO, and email integration.

## Quick Start

```bash
cp .env.example .env   # Edit with your Entra ID + email credentials
docker compose up -d    # Available at http://localhost:8000
```

The first user to log in becomes **Admin**.

---

## Features

### Ticket Management
- Ticket creation via web, email, chat, API, web forms
- Statuses: Open, In Progress, Pending Reminder, Pending Close, Waiting, Resolved, Closed
- Priorities: Low, Medium, High, Critical
- Ticket numbers (YYYYMMDD-NNNN format)
- Agent assignment, group routing
- **Merge tickets** - combine related tickets into one
- **Split tickets** - split an article into a new ticket
- **Link tickets** - parent/child/related relationships
- **Bulk actions** - change status/priority/assignee on multiple tickets
- **Ticket templates** - pre-filled forms for recurring issues
- **Checklists** - per-ticket task lists with checklist templates
- **Tags** - categorize and filter tickets by tag
- **Full audit history** - every change tracked with who/what/when
- **Pending reminders** - set future reminder dates
- **Follow-up detection** - email replies reopen resolved tickets
- **Internal notes** - agent-only articles not visible to customers
- **Custom fields** - JSON custom_fields on tickets, users, organizations

### Communication Channels
- **Email** (IMAP inbound + SMTP outbound, multiple accounts)
- **Live Chat** (WebSocket-based, embeddable widget)
- **Web Forms** (embeddable contact forms, auto-creates tickets)
- **Phone/CTI** (log phone calls as tickets)
- **REST API** (full CRUD for integrations)
- Channel tracking on each ticket/article

### Knowledge Base
- Hierarchical categories
- Three visibility levels: Public, Internal, Draft
- Rich text articles with full editor
- Customer-facing public help center (`/help/`)
- Search across all articles
- Link KB articles to tickets
- Agent/admin management interface

### Automation
- **Triggers** - condition-based actions on ticket create/update
- **Time-based triggers** - actions when conditions met over time
- **Schedulers** - periodic automated actions on matching tickets
- **Macros** - one-click multi-action buttons
- **SLAs** - first response + resolution time targets with escalation
- **Webhooks** - outbound HTTP notifications with HMAC signing

### User & Organization Management
- Roles: Customer, Agent, Admin
- **Groups** - team-based ticket routing with email addresses and signatures
- **Organizations** - group customers by company with domain auto-assignment
- **VIP customers** - flag important customers
- Custom user/organization fields
- User profiles with full interaction history
- **Out-of-office** - set replacement agent

### Overviews & UI
- Customizable ticket overviews (worklists) with configurable columns/sorting/filters
- Overview permissions by role/group
- Full-text search across tickets
- Dashboard with activity stream and statistics
- **Customer portal** (`/portal/`) - dedicated interface for customers
- **Keyboard shortcuts** (Alt+N new ticket, Alt+D dashboard, Alt+S search)
- **Text modules** - `::keyword` snippets in article body
- Responsive design for mobile
- Notifications center (in-app + email)
- **@mentions** - tag colleagues in tickets

### Reporting & Time Accounting
- Ticket statistics dashboard (by status, priority, group, agent)
- Time tracking per ticket with activity types (billable, travel, etc.)
- **CSV export** of time accounting data
- Agent performance stats
- 30-day created/closed counts

### Branding & Customization
- Custom product name
- Custom primary color
- Custom CSS injection
- Per-group email signatures
- **Core Workflows** - dynamic forms (show/hide/require fields based on context)
- **Custom object attributes** - add fields to tickets, users, organizations

### Security & Privacy
- Microsoft Entra ID (Azure AD) SSO via OIDC
- API token authentication (per-user, revocable)
- Session management
- Device tracking
- **GDPR Data Privacy** - right-to-forget deletion requests
- Full audit trail on tickets
- CSRF protection
- Rate limiting ready

### Calendar
- **iCal/CalDAV feed** (`/ical/feed?token=...`) for pending reminders and escalated tickets
- Business hours calendars with timezone support
- Holiday management

### REST API (`/api/v1/`)
- Full ticket CRUD with articles
- User, group, organization management
- Tag management
- Text modules
- Notification management
- Statistics endpoint
- API token generation
- Bearer token authentication

---

## Architecture

| Component | Technology |
|---|---|
| Backend | Python / FastAPI (async) |
| Templates | Jinja2 (server-side rendered) |
| Database | SQLite via aiosqlite (Docker volume) |
| Auth | Microsoft Entra ID / OIDC (authlib) |
| Email | IMAP polling + SMTP (multiple accounts) |
| Chat | WebSocket (FastAPI native) |
| Automation | asyncio background tasks |
| Deployment | Single Docker container |

**No Redis, no Node.js, no separate database server required.**

## Azure AD Setup

1. Azure Portal > App registrations > New registration
2. Redirect URI: `http://yourhost:8000/auth/callback` (Web)
3. API permissions: `openid`, `email`, `profile`
4. Create client secret
5. Set `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`, `ENTRA_TENANT_ID` in `.env`

## Configuration Reference

See `.env.example` for all configuration options.

## File Structure

```
SlateDesk/
├── docker-compose.yml          # Single-command deployment
├── Dockerfile                  # Python 3.12 slim container
├── .env.example                # All configuration documented
├── app/
│   ├── main.py                 # FastAPI app, lifespan, routers
│   ├── config.py               # Pydantic settings
│   ├── database.py             # SQLAlchemy async engine
│   ├── models.py               # 30+ SQLAlchemy models
│   ├── auth/                   # Entra ID OIDC + session deps
│   ├── routes/
│   │   ├── auth.py             # Login/callback/logout
│   │   ├── tickets.py          # Full ticket CRUD + all actions
│   │   ├── admin.py            # 20 admin management sections
│   │   ├── knowledge_base.py   # KB CRUD + public portal
│   │   ├── api.py              # REST API endpoints
│   │   ├── chat.py             # WebSocket live chat
│   │   ├── customer_portal.py  # Customer self-service
│   │   ├── web_forms.py        # Public form submissions
│   │   ├── reporting.py        # Statistics + CSV export
│   │   └── ical.py             # Calendar feed
│   ├── services/
│   │   ├── ticket_service.py   # Business logic
│   │   ├── automation.py       # Triggers, schedulers, SLA
│   │   ├── email_inbound.py    # IMAP polling (multi-account)
│   │   └── email_outbound.py   # SMTP notifications
│   ├── templates/              # 50 Jinja2 templates
│   │   ├── admin/              # 20 admin panel templates
│   │   ├── kb/                 # Knowledge base templates
│   │   ├── chat/               # Chat interface + widget
│   │   ├── portal/             # Customer portal
│   │   ├── forms/              # Web form templates
│   │   └── reports/            # Reporting dashboards
│   └── static/
│       ├── style.css           # Full responsive CSS
│       ├── app.js              # Bulk actions, shortcuts, text modules
│       └── widget.js           # Embeddable chat widget
└── 84 files total
```
