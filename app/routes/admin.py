import json
from datetime import datetime, timezone

import bleach
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.database import get_db
from app.schemas import (
    GroupCreateForm, OrganizationCreateForm, SLACreateForm,
    TriggerCreateForm, MacroCreateForm, WebhookCreateForm,
    TextModuleCreateForm, BrandingForm,
)
from app.models import (
    Ticket, User, UserRole, Group, Organization, SLA, Calendar, Trigger, TriggerEvent,
    Scheduler, Macro, Webhook, TextModule, TicketTemplate, Signature,
    ChecklistTemplate, ObjectAttribute, CoreWorkflow, SystemSetting,
    EmailAccount, WebForm, TicketPriority, DataPrivacyTask, Overview,
)

router = APIRouter(prefix="/admin", tags=["admin"])


# --- Dashboard ---
@router.get("/", response_class=HTMLResponse)
async def admin_panel(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    users = (await db.execute(select(User).order_by(User.display_name))).scalars().all()
    groups = (await db.execute(select(Group).order_by(Group.name))).scalars().all()
    orgs = (await db.execute(select(Organization).order_by(Organization.name))).scalars().all()

    return request.app.state.templates.TemplateResponse("admin/index.html", {
        "request": request, "user": user, "users": users,
        "groups": groups, "organizations": orgs, "roles": list(UserRole),
    })


# --- Users ---
@router.post("/users/{user_id}/role")
async def change_role(
    user_id: int, role: str = Form(...),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404)
    if target.id == user.id:
        raise HTTPException(400, "Cannot change your own role")
    try:
        new_role = UserRole(role)
    except ValueError:
        raise HTTPException(422, f"Invalid role. Must be one of: {', '.join(e.value for e in UserRole)}")
    target.role = new_role
    await db.commit()
    return RedirectResponse(url="/admin/", status_code=302)


@router.post("/users/{user_id}/vip")
async def toggle_vip(
    user_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404)
    target.vip = not target.vip
    await db.commit()
    return RedirectResponse(url="/admin/", status_code=302)


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404)
    if target.id == user.id:
        raise HTTPException(400, "Cannot deactivate yourself")
    target.active = not target.active
    await db.commit()
    # If deactivating, invalidate their sessions by clearing session data
    # (the get_current_user check will also catch this on next request)
    return RedirectResponse(url="/admin/", status_code=302)


@router.post("/users/{user_id}/out-of-office")
async def set_out_of_office(
    user_id: int,
    out_of_office: str = Form("off"),
    replacement_id: int | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404)

    is_ooo = out_of_office in ("on", "true", "1", "yes")

    if is_ooo and replacement_id:
        if replacement_id == user_id:
            raise HTTPException(400, "Cannot set self as replacement")
        replacement = await db.get(User, replacement_id)
        if not replacement:
            raise HTTPException(404, "Replacement user not found")
        if replacement.role == UserRole.customer:
            raise HTTPException(400, "Replacement must be an agent or admin")

    target.out_of_office = is_ooo
    target.out_of_office_replacement_id = replacement_id if is_ooo else None
    await db.commit()
    await db.refresh(target)
    return RedirectResponse(url="/admin/", status_code=302)


@router.post("/users/create")
async def create_user(
    email: str = Form(...),
    display_name: str = Form(...),
    role: str = Form("customer"),
    password: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    import bcrypt
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        return RedirectResponse(url="/admin/?error=Email+already+exists", status_code=302)

    password_hash = None
    if password:
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    new_user = User(
        entra_oid=f"local-{email}",
        email=email,
        display_name=display_name,
        role=UserRole(role),
        password_hash=password_hash,
    )
    db.add(new_user)
    await db.commit()
    return RedirectResponse(url="/admin/", status_code=302)


# --- Groups ---
@router.get("/groups", response_class=HTMLResponse)
async def groups_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    groups = (await db.execute(select(Group).order_by(Group.name))).scalars().all()
    signatures = (await db.execute(select(Signature))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/groups.html", {
        "request": request, "user": user, "groups": groups, "signatures": signatures,
    })


@router.post("/groups")
async def create_group(
    name: str = Form(...), display_name: str = Form(""),
    email_address: str = Form(""), signature_id: int | None = Form(None),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    form = GroupCreateForm(name=name, display_name=display_name, email_address=email_address, signature_id=signature_id)
    normalized_name = form.name.strip().lower().replace(" ", "_")
    existing = await db.execute(select(Group).where(Group.name == normalized_name))
    if existing.scalar_one_or_none():
        raise HTTPException(422, f"Group '{normalized_name}' already exists")
    group = Group(
        name=normalized_name,
        display_name=form.display_name.strip() or form.name.strip(),
        email_address=form.email_address.strip() or None,
        signature_id=form.signature_id,
    )
    db.add(group)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return RedirectResponse(url="/admin/groups?error=Name+already+exists", status_code=302)
    return RedirectResponse(url="/admin/groups", status_code=302)


@router.post("/groups/{group_id}/delete")
async def delete_group(group_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    group = await db.get(Group, group_id)
    if not group:
        raise HTTPException(404)
    # Unassign tickets from this group before deletion
    result = await db.execute(select(Ticket).where(Ticket.group_id == group_id))
    for ticket in result.scalars().all():
        ticket.group_id = None
    await db.delete(group)
    await db.commit()
    return RedirectResponse(url="/admin/groups", status_code=302)


# --- Organizations ---
@router.get("/organizations", response_class=HTMLResponse)
async def organizations_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    orgs = (await db.execute(select(Organization).order_by(Organization.name))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/organizations.html", {
        "request": request, "user": user, "organizations": orgs,
    })


@router.post("/organizations")
async def create_organization(
    name: str = Form(...), domain: str = Form(""),
    domain_assignment: bool = Form(False), shared: bool = Form(True),
    note: str = Form(""),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    form = OrganizationCreateForm(name=name, domain=domain, domain_assignment=domain_assignment, shared=shared, note=note)
    existing = await db.execute(select(Organization).where(Organization.name == form.name.strip()))
    if existing.scalar_one_or_none():
        raise HTTPException(422, f"Organization '{form.name.strip()}' already exists")
    org = Organization(
        name=form.name.strip(), domain=form.domain.strip() or None,
        domain_assignment=form.domain_assignment, shared=form.shared, note=form.note,
    )
    db.add(org)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return RedirectResponse(url="/admin/organizations?error=Name+already+exists", status_code=302)
    return RedirectResponse(url="/admin/organizations", status_code=302)


@router.post("/organizations/{org_id}/delete")
async def delete_organization(org_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404)
    await db.delete(org)
    await db.commit()
    return RedirectResponse(url="/admin/organizations", status_code=302)


# --- SLAs ---
@router.get("/slas", response_class=HTMLResponse)
async def slas_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    slas = (await db.execute(select(SLA))).scalars().all()
    calendars = (await db.execute(select(Calendar))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/slas.html", {
        "request": request, "user": user, "slas": slas, "calendars": calendars,
    })


@router.post("/slas")
async def create_sla(
    name: str = Form(...),
    first_response_time: int | None = Form(None),
    update_time: int | None = Form(None),
    solution_time: int | None = Form(None),
    calendar_id: int | None = Form(None),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    form = SLACreateForm(
        name=name, first_response_time=first_response_time,
        update_time=update_time, solution_time=solution_time,
        calendar_id=calendar_id,
    )
    sla = SLA(
        name=form.name, first_response_time=form.first_response_time,
        update_time=form.update_time, solution_time=form.solution_time,
        calendar_id=form.calendar_id,
    )
    db.add(sla)
    await db.commit()
    return RedirectResponse(url="/admin/slas", status_code=302)


# --- Calendars ---
@router.get("/calendars", response_class=HTMLResponse)
async def calendars_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    calendars = (await db.execute(select(Calendar))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/calendars.html", {
        "request": request, "user": user, "calendars": calendars,
    })


@router.post("/calendars")
async def create_calendar(
    name: str = Form(...), timezone: str = Form("UTC"),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    cal = Calendar(name=name, timezone=timezone)
    db.add(cal)
    await db.commit()
    return RedirectResponse(url="/admin/calendars", status_code=302)


# --- Triggers ---
@router.get("/triggers", response_class=HTMLResponse)
async def triggers_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    triggers = (await db.execute(select(Trigger).order_by(Trigger.position))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/triggers.html", {
        "request": request, "user": user, "triggers": triggers,
        "events": list(TriggerEvent),
    })


@router.post("/triggers")
async def create_trigger(
    name: str = Form(...), event: str = Form(...),
    conditions: str = Form("{}"), actions: str = Form("[]"),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    form = TriggerCreateForm(name=name, event=event, conditions=conditions, actions=actions)
    try:
        parsed_conditions = json.loads(form.conditions) if form.conditions else {}
        parsed_actions = json.loads(form.actions) if form.actions else []
    except json.JSONDecodeError:
        raise HTTPException(422, "Invalid JSON in conditions or actions")
    try:
        event = TriggerEvent(form.event)
    except ValueError:
        raise HTTPException(422, f"Invalid event. Must be one of: {', '.join(e.value for e in TriggerEvent)}")
    trigger = Trigger(
        name=form.name, event=event,
        conditions=parsed_conditions, actions=parsed_actions,
    )
    db.add(trigger)
    await db.commit()
    return RedirectResponse(url="/admin/triggers", status_code=302)


@router.post("/triggers/{trigger_id}/toggle")
async def toggle_trigger(trigger_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    trigger = await db.get(Trigger, trigger_id)
    if trigger:
        trigger.active = not trigger.active
        await db.commit()
    return RedirectResponse(url="/admin/triggers", status_code=302)


# --- Schedulers ---
@router.get("/schedulers", response_class=HTMLResponse)
async def schedulers_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    schedulers = (await db.execute(select(Scheduler))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/schedulers.html", {
        "request": request, "user": user, "schedulers": schedulers,
    })


@router.post("/schedulers")
async def create_scheduler(
    name: str = Form(...), interval_minutes: int = Form(60),
    conditions: str = Form("{}"), actions: str = Form("[]"),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    if interval_minutes < 1:
        raise HTTPException(422, "interval_minutes must be at least 1")
    try:
        parsed_conditions = json.loads(conditions) if conditions else {}
        parsed_actions = json.loads(actions) if actions else []
    except json.JSONDecodeError:
        raise HTTPException(422, "Invalid JSON in conditions or actions")
    sched = Scheduler(
        name=name, interval_minutes=interval_minutes,
        conditions=parsed_conditions, actions=parsed_actions,
    )
    db.add(sched)
    await db.commit()
    return RedirectResponse(url="/admin/schedulers", status_code=302)


# --- Macros ---
@router.get("/macros", response_class=HTMLResponse)
async def macros_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    macros = (await db.execute(select(Macro))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/macros.html", {
        "request": request, "user": user, "macros": macros,
    })


@router.post("/macros")
async def create_macro(
    name: str = Form(...), actions: str = Form("[]"), note: str = Form(""),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    form = MacroCreateForm(name=name, actions=actions, note=note)
    try:
        parsed_actions = json.loads(form.actions) if form.actions else []
    except json.JSONDecodeError:
        raise HTTPException(422, "Invalid JSON in actions")
    macro = Macro(name=form.name, actions=parsed_actions, note=form.note)
    db.add(macro)
    await db.commit()
    return RedirectResponse(url="/admin/macros", status_code=302)


# --- Webhooks ---
@router.get("/webhooks", response_class=HTMLResponse)
async def webhooks_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    webhooks = (await db.execute(select(Webhook))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/webhooks.html", {
        "request": request, "user": user, "webhooks": webhooks,
    })


@router.post("/webhooks")
async def create_webhook(
    name: str = Form(...), endpoint: str = Form(...),
    signature_token: str = Form(""),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    form = WebhookCreateForm(name=name, endpoint=endpoint, signature_token=signature_token)
    if not form.endpoint.startswith(("http://", "https://")):
        raise HTTPException(422, "Webhook endpoint must start with http:// or https://")
    wh = Webhook(name=form.name, endpoint=form.endpoint, signature_token=form.signature_token or None)
    db.add(wh)
    await db.commit()
    return RedirectResponse(url="/admin/webhooks", status_code=302)


# --- Text Modules ---
@router.get("/text-modules", response_class=HTMLResponse)
async def text_modules_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    modules = (await db.execute(select(TextModule))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/text_modules.html", {
        "request": request, "user": user, "modules": modules,
    })


@router.post("/text-modules")
async def create_text_module(
    name: str = Form(...), keyword: str = Form(...), content: str = Form(...),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    form = TextModuleCreateForm(name=name, keyword=keyword, content=content)
    SAFE_TAGS = ["p", "br", "b", "i", "u", "a", "ul", "ol", "li", "pre", "code", "strong", "em", "blockquote"]
    sanitized_content = bleach.clean(form.content, tags=SAFE_TAGS, strip=True)
    existing = await db.execute(select(TextModule).where(TextModule.keyword == form.keyword))
    if existing.scalar_one_or_none():
        raise HTTPException(422, f"Keyword '{form.keyword}' already exists")
    tm = TextModule(name=form.name, keyword=form.keyword, content=sanitized_content)
    db.add(tm)
    await db.commit()
    return RedirectResponse(url="/admin/text-modules", status_code=302)


# --- Ticket Templates ---
@router.get("/ticket-templates", response_class=HTMLResponse)
async def ticket_templates_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    templates_list = (await db.execute(select(TicketTemplate))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/ticket_templates.html", {
        "request": request, "user": user, "templates": templates_list,
    })


@router.post("/ticket-templates")
async def create_ticket_template(
    name: str = Form(...), subject: str = Form(""), body: str = Form(""),
    priority: str = Form("medium"),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    try:
        prio = TicketPriority(priority)
    except ValueError:
        raise HTTPException(422, f"Invalid priority. Must be one of: {', '.join(e.value for e in TicketPriority)}")
    tt = TicketTemplate(name=name, subject=subject, body=body, priority=prio)
    db.add(tt)
    await db.commit()
    return RedirectResponse(url="/admin/ticket-templates", status_code=302)


# --- Signatures ---
@router.get("/signatures", response_class=HTMLResponse)
async def signatures_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    sigs = (await db.execute(select(Signature))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/signatures.html", {
        "request": request, "user": user, "signatures": sigs,
    })


@router.post("/signatures")
async def create_signature(
    name: str = Form(...), body_html: str = Form(""),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    sig = Signature(name=name, body_html=body_html)
    db.add(sig)
    await db.commit()
    return RedirectResponse(url="/admin/signatures", status_code=302)


# --- Checklist Templates ---
@router.get("/checklist-templates", response_class=HTMLResponse)
async def checklist_templates_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    templates_list = (await db.execute(select(ChecklistTemplate))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/checklist_templates.html", {
        "request": request, "user": user, "templates": templates_list,
    })


@router.post("/checklist-templates")
async def create_checklist_template(
    name: str = Form(...), items: str = Form(""),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    try:
        parsed_items = json.loads(items) if items else []
    except json.JSONDecodeError:
        raise HTTPException(422, "Invalid JSON in items")
    ct = ChecklistTemplate(name=name, items=parsed_items)
    db.add(ct)
    await db.commit()
    return RedirectResponse(url="/admin/checklist-templates", status_code=302)


# --- Object Attributes ---
@router.get("/object-attributes", response_class=HTMLResponse)
async def object_attributes_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    attrs = (await db.execute(select(ObjectAttribute).order_by(ObjectAttribute.object_type, ObjectAttribute.position))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/object_attributes.html", {
        "request": request, "user": user, "attributes": attrs,
    })


@router.post("/object-attributes")
async def create_object_attribute(
    object_type: str = Form(...), name: str = Form(...),
    display_name: str = Form(...), data_type: str = Form("input"),
    required: bool = Form(False), data_options: str = Form("{}"),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    # Validate object_type
    if object_type not in ("ticket", "user", "organization"):
        raise HTTPException(422, "object_type must be ticket, user, or organization")
    # Validate data_type
    valid_types = ("input", "select", "boolean", "date", "datetime", "integer", "textarea")
    if data_type not in valid_types:
        raise HTTPException(422, f"data_type must be one of: {', '.join(valid_types)}")
    # Validate name is not empty
    if not name.strip():
        raise HTTPException(422, "name must not be empty")
    try:
        parsed_options = json.loads(data_options) if data_options else {}
    except json.JSONDecodeError:
        raise HTTPException(422, "Invalid JSON in data_options")
    # Check for duplicate name within the same object_type
    existing = await db.execute(
        select(ObjectAttribute).where(
            ObjectAttribute.object_type == object_type,
            ObjectAttribute.name == name.strip(),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(422, f"Attribute '{name.strip()}' already exists for {object_type}")
    attr = ObjectAttribute(
        object_type=object_type, name=name.strip(), display_name=display_name.strip(),
        data_type=data_type, required=required,
        data_options=parsed_options,
    )
    db.add(attr)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return RedirectResponse(url="/admin/object-attributes?error=Name+already+exists", status_code=302)
    return RedirectResponse(url="/admin/object-attributes", status_code=302)


@router.post("/object-attributes/{attr_id}/delete")
async def delete_object_attribute(
    attr_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    attr = await db.get(ObjectAttribute, attr_id)
    if not attr:
        raise HTTPException(404)
    await db.delete(attr)
    await db.commit()
    return RedirectResponse(url="/admin/object-attributes", status_code=302)


# --- Core Workflows ---
@router.get("/core-workflows", response_class=HTMLResponse)
async def core_workflows_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    workflows = (await db.execute(select(CoreWorkflow).order_by(CoreWorkflow.position))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/core_workflows.html", {
        "request": request, "user": user, "workflows": workflows,
    })


@router.post("/core-workflows")
async def create_core_workflow(
    name: str = Form(...), object_type: str = Form("ticket"),
    conditions: str = Form("{}"), actions: str = Form("[]"),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    try:
        parsed_conditions = json.loads(conditions) if conditions else {}
        parsed_actions = json.loads(actions) if actions else []
    except json.JSONDecodeError:
        raise HTTPException(422, "Invalid JSON in conditions or actions")
    wf = CoreWorkflow(
        name=name, object_type=object_type,
        conditions=parsed_conditions, actions=parsed_actions,
    )
    db.add(wf)
    await db.commit()
    return RedirectResponse(url="/admin/core-workflows", status_code=302)


# --- Overviews ---
@router.get("/overviews", response_class=HTMLResponse)
async def overviews_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    overviews = (await db.execute(select(Overview).order_by(Overview.position))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/overviews.html", {
        "request": request, "user": user, "overviews": overviews,
    })


@router.post("/overviews")
async def create_overview(
    name: str = Form(...), link: str = Form(""),
    conditions: str = Form("{}"), order_by: str = Form("created_at"),
    order_direction: str = Form("desc"), columns: str = Form("[]"),
    roles: str = Form("[]"),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    try:
        parsed_conditions = json.loads(conditions) if conditions else {}
        parsed_columns = json.loads(columns) if columns else ["number", "subject", "status", "priority", "assignee", "updated_at"]
        parsed_roles = json.loads(roles) if roles else []
    except json.JSONDecodeError:
        raise HTTPException(422, "Invalid JSON in conditions, columns, or roles")
    ov = Overview(
        name=name, link=link or name.lower().replace(" ", "-"),
        conditions=parsed_conditions, order_by=order_by,
        order_direction=order_direction,
        columns=parsed_columns,
        roles=parsed_roles,
    )
    db.add(ov)
    await db.commit()
    return RedirectResponse(url="/admin/overviews", status_code=302)


@router.post("/overviews/{overview_id}/delete")
async def delete_overview(overview_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    obj = await db.get(Overview, overview_id)
    if not obj:
        raise HTTPException(404)
    await db.delete(obj)
    await db.commit()
    return RedirectResponse(url="/admin/overviews", status_code=302)


# --- Delete routes for triggers, schedulers, SLAs, webhooks, macros ---


@router.post("/triggers/{trigger_id}/delete")
async def delete_trigger(trigger_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    obj = await db.get(Trigger, trigger_id)
    if not obj:
        raise HTTPException(404)
    await db.delete(obj)
    await db.commit()
    return RedirectResponse(url="/admin/triggers", status_code=302)


@router.post("/schedulers/{scheduler_id}/delete")
async def delete_scheduler(scheduler_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    obj = await db.get(Scheduler, scheduler_id)
    if not obj:
        raise HTTPException(404)
    await db.delete(obj)
    await db.commit()
    return RedirectResponse(url="/admin/schedulers", status_code=302)


@router.post("/schedulers/{scheduler_id}/toggle")
async def toggle_scheduler(scheduler_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    sched = await db.get(Scheduler, scheduler_id)
    if sched:
        sched.active = not sched.active
        await db.commit()
    return RedirectResponse(url="/admin/schedulers", status_code=302)


@router.post("/slas/{sla_id}/delete")
async def delete_sla(sla_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    sla = await db.get(SLA, sla_id)
    if not sla:
        raise HTTPException(404)
    # Unassign from tickets
    result = await db.execute(select(Ticket).where(Ticket.sla_id == sla_id))
    for ticket in result.scalars().all():
        ticket.sla_id = None
    await db.delete(sla)
    await db.commit()
    return RedirectResponse(url="/admin/slas", status_code=302)


@router.post("/webhooks/{webhook_id}/delete")
async def delete_webhook(webhook_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    obj = await db.get(Webhook, webhook_id)
    if not obj:
        raise HTTPException(404)
    await db.delete(obj)
    await db.commit()
    return RedirectResponse(url="/admin/webhooks", status_code=302)


@router.post("/macros/{macro_id}/delete")
async def delete_macro(macro_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    obj = await db.get(Macro, macro_id)
    if not obj:
        raise HTTPException(404)
    await db.delete(obj)
    await db.commit()
    return RedirectResponse(url="/admin/macros", status_code=302)


# --- Email Accounts ---
@router.get("/email-accounts", response_class=HTMLResponse)
async def email_accounts_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    accounts = (await db.execute(select(EmailAccount))).scalars().all()
    groups = (await db.execute(select(Group))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/email_accounts.html", {
        "request": request, "user": user, "accounts": accounts, "groups": groups,
    })


@router.post("/email-accounts")
async def create_email_account(
    name: str = Form(...), email_address: str = Form(...),
    group_id: int | None = Form(None),
    imap_host: str = Form(""), imap_port: int = Form(993),
    imap_user: str = Form(""), imap_password: str = Form(""),
    smtp_host: str = Form(""), smtp_port: int = Form(587),
    smtp_user: str = Form(""), smtp_password: str = Form(""),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    acc = EmailAccount(
        name=name, email_address=email_address, group_id=group_id,
        imap_host=imap_host or None, imap_port=imap_port,
        imap_user=imap_user or None, imap_password=imap_password or None,
        smtp_host=smtp_host or None, smtp_port=smtp_port,
        smtp_user=smtp_user or None, smtp_password=smtp_password or None,
    )
    db.add(acc)
    await db.commit()
    return RedirectResponse(url="/admin/email-accounts", status_code=302)


# --- Web Forms ---
@router.get("/web-forms", response_class=HTMLResponse)
async def web_forms_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    forms = (await db.execute(select(WebForm))).scalars().all()
    groups = (await db.execute(select(Group))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/web_forms.html", {
        "request": request, "user": user, "forms": forms, "groups": groups,
    })


@router.post("/web-forms")
async def create_web_form(
    request: Request,
    name: str = Form(...), title: str = Form("Contact Us"),
    group_id: int | None = Form(None),
    success_message: str = Form("Thank you! Your request has been submitted."),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    form = WebForm(
        name=name, title=title, group_id=group_id,
        success_message=success_message,
        fields=[
            {"name": "name", "label": "Name", "type": "text", "required": True},
            {"name": "email", "label": "Email", "type": "email", "required": True},
            {"name": "subject", "label": "Subject", "type": "text", "required": True},
            {"name": "message", "label": "Message", "type": "textarea", "required": True},
        ],
    )
    db.add(form)
    await db.flush()
    form.embed_code = f'<script src="{request.base_url}static/widget.js" data-form-id="{form.id}"></script>'
    await db.commit()
    return RedirectResponse(url="/admin/web-forms", status_code=302)


# --- Branding / Settings ---
@router.get("/branding", response_class=HTMLResponse)
async def branding_settings(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    settings = {}
    for key in ["product_name", "product_logo", "primary_color", "custom_css"]:
        result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
        s = result.scalar_one_or_none()
        settings[key] = s.value if s else ""
    return request.app.state.templates.TemplateResponse("admin/branding.html", {
        "request": request, "user": user, "settings": settings,
    })


@router.post("/branding")
async def save_branding(
    request: Request,
    product_name: str = Form("DeskFlow"),
    primary_color: str = Form("#2563eb"),
    custom_css: str = Form(""),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    form = BrandingForm(product_name=product_name, primary_color=primary_color, custom_css=custom_css)
    for key, value in [("product_name", form.product_name), ("primary_color", form.primary_color), ("custom_css", form.custom_css)]:
        result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = value
        else:
            db.add(SystemSetting(key=key, value=value))
    await db.commit()
    # Update cached branding
    request.app.state.app_name = form.product_name
    request.app.state.primary_color = form.primary_color
    request.app.state.custom_css = form.custom_css
    return RedirectResponse(url="/admin/branding", status_code=302)


# --- GDPR Data Privacy ---
@router.get("/data-privacy", response_class=HTMLResponse)
async def data_privacy(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    tasks = (await db.execute(select(DataPrivacyTask).order_by(DataPrivacyTask.created_at.desc()))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/data_privacy.html", {
        "request": request, "user": user, "tasks": tasks,
    })


@router.post("/data-privacy/delete-user/{user_id}")
async def create_privacy_deletion(
    user_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    target = await db.get(User, user_id)
    if not target or target.id == user.id:
        raise HTTPException(400, "Cannot delete yourself or non-existent user")

    task = DataPrivacyTask(
        deletable_type="user", deletable_id=user_id,
        requested_by_id=user.id,
    )
    db.add(task)
    await db.commit()
    return RedirectResponse(url="/admin/data-privacy", status_code=302)


# --- Invitations ---
@router.get("/invitations", response_class=HTMLResponse)
async def invitations_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    from app.models import Invitation
    invitations = (await db.execute(
        select(Invitation).order_by(Invitation.created_at.desc())
    )).scalars().all()
    groups = (await db.execute(select(Group))).scalars().all()
    orgs = (await db.execute(select(Organization))).scalars().all()
    return request.app.state.templates.TemplateResponse("admin/invitations.html", {
        "request": request, "user": user, "invitations": invitations,
        "groups": groups, "organizations": orgs, "roles": list(UserRole),
        "now": datetime.now(timezone.utc),
    })


@router.post("/invitations")
async def create_invitation(
    email: str = Form(...),
    role: str = Form("customer"),
    group_id: int | None = Form(None),
    organization_id: int | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    import secrets
    from datetime import timedelta
    from app.models import Invitation
    from app.config import settings

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.INVITE_EXPIRY_DAYS)

    invitation = Invitation(
        email=email,
        role=UserRole(role),
        group_id=group_id,
        organization_id=organization_id,
        token=token,
        invited_by_id=user.id,
        expires_at=expires_at,
    )
    db.add(invitation)
    await db.commit()
    return RedirectResponse(url="/admin/invitations", status_code=302)
