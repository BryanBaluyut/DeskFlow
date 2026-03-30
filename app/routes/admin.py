from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin, require_agent
from app.auth.passwords import hash_password, validate_password
from app.config import settings
from app.database import get_db
from app.models import (
    User, UserRole, Group, Organization, Tag, SLA, Calendar, Trigger, TriggerEvent,
    Scheduler, Macro, Webhook, TextModule, TicketTemplate, Signature,
    ChecklistTemplate, ObjectAttribute, CoreWorkflow, SystemSetting,
    EmailAccount, WebForm, TicketPriority, TicketStatus,
    DataPrivacyTask, Overview,
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
        "entra_configured": bool(settings.ENTRA_CLIENT_ID),
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
    target.role = UserRole(role)
    await db.commit()
    return RedirectResponse(url="/admin/", status_code=302)


@router.post("/users/{user_id}/vip")
async def toggle_vip(
    user_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    target = await db.get(User, user_id)
    if target:
        target.vip = not target.vip
        await db.commit()
    return RedirectResponse(url="/admin/", status_code=302)


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    target = await db.get(User, user_id)
    if target and target.id != user.id:
        target.active = not target.active
        await db.commit()
    return RedirectResponse(url="/admin/", status_code=302)


@router.post("/users")
async def create_user(
    request: Request,
    display_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("customer"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    pwd_errors = validate_password(password)
    if pwd_errors:
        raise HTTPException(400, detail="; ".join(pwd_errors))

    existing = await db.execute(select(User).where(User.email == email.strip().lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(400, detail="A user with this email already exists.")

    new_user = User(
        display_name=display_name.strip(),
        email=email.strip().lower(),
        password_hash=hash_password(password),
        auth_method="local",
        role=UserRole(role),
        active=True,
    )
    db.add(new_user)
    await db.commit()
    return RedirectResponse(url="/admin/", status_code=302)


@router.post("/users/{user_id}/password")
async def reset_password(
    user_id: int,
    new_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    pwd_errors = validate_password(new_password)
    if pwd_errors:
        raise HTTPException(400, detail="; ".join(pwd_errors))

    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404)
    target.password_hash = hash_password(new_password)
    target.auth_method = "local"
    await db.commit()
    return RedirectResponse(url="/admin/", status_code=302)


@router.post("/users/{user_id}/auth-method")
async def change_auth_method(
    user_id: int,
    auth_method: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    if auth_method not in ("local", "oauth"):
        raise HTTPException(400, detail="Invalid auth method.")
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404)
    if auth_method == "local" and not target.password_hash:
        raise HTTPException(400, detail="Set a password before switching to local auth.")
    target.auth_method = auth_method
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
    email_address: str = Form(""), signature_id: str = Form(""),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    group = Group(
        name=name.strip().lower().replace(" ", "_"),
        display_name=display_name.strip() or name.strip(),
        email_address=email_address.strip() or None,
        signature_id=int(signature_id) if signature_id else None,
    )
    db.add(group)
    await db.commit()
    return RedirectResponse(url="/admin/groups", status_code=302)


@router.post("/groups/{group_id}/delete")
async def delete_group(group_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    group = await db.get(Group, group_id)
    if group:
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
    org = Organization(
        name=name.strip(), domain=domain.strip() or None,
        domain_assignment=domain_assignment, shared=shared, note=note,
    )
    db.add(org)
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
    sla = SLA(
        name=name, first_response_time=first_response_time,
        update_time=update_time, solution_time=solution_time,
        calendar_id=calendar_id,
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
    import json
    trigger = Trigger(
        name=name, event=TriggerEvent(event),
        conditions=json.loads(conditions), actions=json.loads(actions),
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
    import json
    sched = Scheduler(
        name=name, interval_minutes=interval_minutes,
        conditions=json.loads(conditions), actions=json.loads(actions),
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
    import json
    macro = Macro(name=name, actions=json.loads(actions), note=note)
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
    wh = Webhook(name=name, endpoint=endpoint, signature_token=signature_token or None)
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
    tm = TextModule(name=name, keyword=keyword, content=content)
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
    tt = TicketTemplate(name=name, subject=subject, body=body, priority=TicketPriority(priority))
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
    import json
    ct = ChecklistTemplate(name=name, items=json.loads(items) if items else [])
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
    import json
    attr = ObjectAttribute(
        object_type=object_type, name=name, display_name=display_name,
        data_type=data_type, required=required,
        data_options=json.loads(data_options) if data_options else {},
    )
    db.add(attr)
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
    import json
    wf = CoreWorkflow(
        name=name, object_type=object_type,
        conditions=json.loads(conditions), actions=json.loads(actions),
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
    import json
    ov = Overview(
        name=name, link=link or name.lower().replace(" ", "-"),
        conditions=json.loads(conditions), order_by=order_by,
        order_direction=order_direction,
        columns=json.loads(columns) if columns else ["number", "subject", "status", "priority", "assignee", "updated_at"],
        roles=json.loads(roles) if roles else [],
    )
    db.add(ov)
    await db.commit()
    return RedirectResponse(url="/admin/overviews", status_code=302)


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
    auth_type: str = Form("basic"),
    imap_host: str = Form(""), imap_port: int = Form(993),
    imap_user: str = Form(""), imap_password: str = Form(""),
    smtp_host: str = Form(""), smtp_port: int = Form(587),
    smtp_user: str = Form(""), smtp_password: str = Form(""),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    acc = EmailAccount(
        name=name, email_address=email_address, group_id=group_id,
        auth_type=auth_type if auth_type in ("basic", "oauth2") else "basic",
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
    group_id: str = Form(""),
    success_message: str = Form("Thank you! Your request has been submitted."),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    form = WebForm(
        name=name, title=title, group_id=int(group_id) if group_id else None,
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
    product_name: str = Form("SlateDesk"),
    primary_color: str = Form("#2563eb"),
    custom_css: str = Form(""),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin),
):
    for key, value in [("product_name", product_name), ("primary_color", primary_color), ("custom_css", custom_css)]:
        result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = value
        else:
            db.add(SystemSetting(key=key, value=value))
    await db.commit()
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
