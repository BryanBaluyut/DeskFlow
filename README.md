# DeskFlow - IT Help Desk Ticketing System

A comprehensive, Docker-deployable IT help desk ticketing system with enterprise-grade features, Microsoft Entra ID SSO, and email integration.

## Quick Start

```bash
cp .env.example .env    # Edit with your credentials
docker compose up -d    # Available at https://localhost
```

On first visit, a **setup wizard** guides you through creating an admin account, setting branding, and creating your first support group.

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

### Authentication
- **Local email/password** - bcrypt-hashed, works without any SSO provider
- **Microsoft Entra ID (Azure AD)** SSO via OIDC (optional)
- Dual auth - both methods available simultaneously
- **User invitations** - admin sends invite link, user sets password
- **First-run setup wizard** - guided 5-step initial configuration
- API token authentication (per-user, revocable)

### Security & Privacy
- **CSRF protection** - starlette-csrf with double-submit cookie pattern
- **Rate limiting** - configurable per-endpoint via slowapi
- **Security headers** - CSP, HSTS, X-Frame-Options, X-Content-Type-Options
- **Input validation** - Pydantic schemas on all form and API inputs
- **XSS prevention** - bleach HTML sanitization with allowlisted tags
- **Automatic HTTPS** - Caddy reverse proxy with Let's Encrypt certificates
- Session cookies with Secure flag, SameSite=Lax, 24h expiry
- **GDPR Data Privacy** - right-to-forget deletion requests
- Full audit trail on tickets
- Device tracking

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
| Backend | Python 3.12 / FastAPI (fully async) |
| Templates | Jinja2 (server-side rendered) |
| Database | PostgreSQL 16 (asyncpg) or SQLite (aiosqlite) |
| Migrations | Alembic (async) |
| Auth | Local (bcrypt) + Microsoft Entra ID / OIDC |
| Email | IMAP polling + SMTP (multiple accounts) |
| Chat | WebSocket (FastAPI native) |
| Automation | asyncio background tasks |
| Logging | structlog (JSON / console) |
| Reverse Proxy | Caddy 2 (automatic TLS) |
| Deployment | Docker Compose (Caddy + App + PostgreSQL) |

**No Redis, no Node.js, no build step required.**

## Production Deployment

1. Set `APP_DOMAIN=helpdesk.yourdomain.com` in `.env`
2. Point DNS to your server
3. Ensure ports 80 and 443 are open
4. `docker compose up -d`

Caddy automatically provisions and renews Let's Encrypt certificates. For local development, `APP_DOMAIN=localhost` uses a self-signed certificate.

## Azure AD Setup (Optional)

DeskFlow works with local email/password authentication out of the box. To add Microsoft SSO:

1. Azure Portal > App registrations > New registration
2. Redirect URI: `https://yourhost/auth/callback` (Web)
3. API permissions: `openid`, `email`, `profile`
4. Create client secret
5. Set `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`, `ENTRA_TENANT_ID` in `.env`

Both local and SSO authentication can be active simultaneously.

## Configuration Reference

See `.env.example` for all configuration options.

## File Structure

```
DeskFlow/
├── docker-compose.yml          # Caddy + App + PostgreSQL
├── Caddyfile                   # Reverse proxy with auto-TLS
├── Dockerfile                  # Multi-stage Python 3.12 (non-root)
├── .env.example                # All configuration documented
├── alembic/                    # Database migrations
├── app/
│   ├── main.py                 # FastAPI app, middleware, routers
│   ├── config.py               # Pydantic settings
│   ├── database.py             # Async engine (PostgreSQL/SQLite)
│   ├── models.py               # 30+ SQLAlchemy models
│   ├── schemas.py              # Pydantic input validation
│   ├── middleware.py            # Security headers, request ID
│   ├── logging_config.py       # structlog configuration
│   ├── rate_limit.py           # Shared slowapi limiter
│   ├── auth/                   # Entra ID OIDC + local auth
│   ├── routes/
│   │   ├── auth.py             # Login (local + SSO), invitations
│   │   ├── setup.py            # First-run setup wizard
│   │   ├── health.py           # Health check endpoint
│   │   ├── tickets.py          # Full ticket CRUD + all actions
│   │   ├── admin.py            # Admin panel + user invitations
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
│   ├── templates/              # 55+ Jinja2 templates
│   └── static/                 # CSS, JS (no build step)
└── tests/                      # pytest test suite
```
