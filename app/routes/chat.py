"""Live chat with WebSocket support."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db, async_session
from app.models import (
    ChatSession, ChatMessage, Ticket, Article, TicketChannel, User,
)
from app.auth.dependencies import require_agent
from app.services.ticket_service import generate_ticket_number, record_history

router = APIRouter(prefix="/chat", tags=["chat"])

# Active WebSocket connections
active_connections: dict[int, list[WebSocket]] = {}  # session_id -> [websockets]


@router.get("/", response_class=HTMLResponse)
async def chat_overview(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_agent)):
    sessions = (await db.execute(
        select(ChatSession).options(
            selectinload(ChatSession.customer), selectinload(ChatSession.agent),
        ).where(ChatSession.state.in_(["waiting", "active"]))
        .order_by(ChatSession.created_at)
    )).scalars().all()
    return request.app.state.templates.TemplateResponse("chat/overview.html", {
        "request": request, "user": user, "sessions": sessions,
    })


@router.post("/{session_id}/accept")
async def accept_chat(session_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require_agent)):
    session = await db.get(ChatSession, session_id)
    if not session or session.state != "waiting":
        raise HTTPException(404)
    session.agent_id = user.id
    session.state = "active"
    await db.commit()

    # Notify via websocket
    if session_id in active_connections:
        for ws in active_connections[session_id]:
            try:
                await ws.send_json({"type": "agent_joined", "agent": user.display_name})
            except Exception:
                pass

    return RedirectResponse(url=f"/chat/{session_id}", status_code=302)


@router.get("/{session_id}", response_class=HTMLResponse)
async def chat_session_view(
    request: Request, session_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_agent),
):
    session = await db.get(ChatSession, session_id, options=[
        selectinload(ChatSession.messages).selectinload(ChatMessage.sender),
        selectinload(ChatSession.customer),
    ])
    if not session:
        raise HTTPException(404)
    return request.app.state.templates.TemplateResponse("chat/session.html", {
        "request": request, "user": user, "chat_session": session,
    })


@router.post("/{session_id}/close")
async def close_chat(session_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require_agent)):
    session = await db.get(ChatSession, session_id, options=[
        selectinload(ChatSession.messages),
    ])
    if not session:
        raise HTTPException(404)

    session.state = "closed"
    session.closed_at = datetime.now(timezone.utc)

    # Create ticket from chat
    number = await generate_ticket_number(db)
    ticket = Ticket(
        number=number,
        subject=f"Chat with {session.visitor_name or 'Visitor'}",
        body_html="<p>Ticket created from live chat session.</p>",
        creator_id=session.customer_id or user.id,
        channel=TicketChannel.chat,
    )
    db.add(ticket)
    await db.flush()

    # Add chat transcript as article
    transcript = "\n".join(
        f"[{m.sender_type}] {m.body}" for m in session.messages
    )
    article = Article(
        ticket_id=ticket.id, author_id=user.id,
        body_html=f"<pre>{transcript}</pre>",
        channel=TicketChannel.chat, sender="system",
    )
    db.add(article)
    session.ticket_id = ticket.id

    await record_history(db, ticket.id, user.id, "created", "channel", None, "chat")
    await db.commit()

    # Notify websocket
    if session_id in active_connections:
        for ws in active_connections[session_id]:
            try:
                await ws.send_json({"type": "closed", "ticket_id": ticket.id})
            except Exception:
                pass

    return RedirectResponse(url=f"/tickets/{ticket.id}", status_code=302)


@router.websocket("/ws/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: int):
    await websocket.accept()

    if session_id not in active_connections:
        active_connections[session_id] = []
    active_connections[session_id].append(websocket)

    try:
        while True:
            data = await websocket.receive_json()
            body = data.get("body", "")
            sender_type = data.get("sender_type", "customer")
            sender_id = data.get("sender_id")

            async with async_session() as db:
                msg = ChatMessage(
                    session_id=session_id, sender_id=sender_id,
                    body=body, sender_type=sender_type,
                )
                db.add(msg)
                await db.commit()

            # Broadcast to all connections
            for ws in active_connections.get(session_id, []):
                if ws != websocket:
                    try:
                        await ws.send_json({
                            "type": "message", "body": body,
                            "sender_type": sender_type,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                    except Exception:
                        pass

    except WebSocketDisconnect:
        if session_id in active_connections:
            active_connections[session_id].remove(websocket)
            if not active_connections[session_id]:
                del active_connections[session_id]


# --- Public chat widget endpoint ---
public_chat_router = APIRouter(prefix="/chat", tags=["chat_widget"])


@public_chat_router.get("/widget", response_class=HTMLResponse)
async def chat_widget(request: Request, db: AsyncSession = Depends(get_db)):
    return request.app.state.templates.TemplateResponse("chat/widget.html", {
        "request": request,
    })


@public_chat_router.post("/widget/start")
async def start_chat(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    name = form.get("name", "Visitor")
    email = form.get("email", "")

    session = ChatSession(visitor_name=name, visitor_email=email)
    db.add(session)
    await db.commit()
    await db.refresh(session)

    return {"session_id": session.id}
