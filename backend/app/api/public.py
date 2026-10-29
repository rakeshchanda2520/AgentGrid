"""Unauthenticated surfaces: branding, the embeddable widget, channel webhooks, and the API-key REST channel."""

import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app import channels, conversations, db, realtime, templates
from app.auth import api_key_tenant
from app.config import BACKEND_DIR
from app.security import decrypt, rate_limited, verify_meta_signature

router = APIRouter(tags=["public"])
DEFAULT_BRAND = {
    "product_name": "AgentGrid",
    "primary_color": "#172554",
    "accent_color": "#C19A5B",
    "logo_url": None,
    "hide_powered_by": False,
    "support_email": None,
}
VISITOR = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


async def brand_for(c, tenant_id: UUID) -> dict[str, Any]:
    rows = await c.fetch(
        """with recursive chain as (select id, parent_id, branding, 0 as depth from tenants where id = $1
             union all select t.id, t.parent_id, t.branding, chain.depth + 1 from tenants t join chain on t.id = chain.parent_id)
           select branding from chain order by depth desc""",
        tenant_id,
    )
    brand = dict(DEFAULT_BRAND)
    for r in rows:  # platform → agency → client: nearest wins
        brand |= {k: v for k, v in (r["branding"] or {}).items() if v not in (None, "")}
    return brand


@router.get("/public/branding")
async def branding(slug: str | None = None) -> dict:
    if not slug:
        return DEFAULT_BRAND
    async with db.tx(system=True) as c:
        tid = await c.fetchval("select id from tenants where slug = $1", slug)
        return (await brand_for(c, tid)) | {"slug": slug} if tid else DEFAULT_BRAND


async def _agent_by_key(key: str) -> dict[str, Any]:
    async with db.tx(system=True) as c:
        a = db.row(
            await c.fetchrow(
                "select a.id, a.tenant_id, a.name, a.config, a.status, t.name as company, t.settings from agents a join tenants t on t.id = a.tenant_id where a.public_key = $1",
                key,
            )
        )
        if not a or a["status"] != "active":
            raise HTTPException(404, "Unknown or paused agent")
        a["brand"] = await brand_for(c, a["tenant_id"])
    return a


@router.get("/public/widget/{key}/config")
async def widget_config(key: str) -> dict:
    a = await _agent_by_key(key)
    cfg = a["config"]
    return {
        "agent_name": a["name"],
        "company": a["company"],
        "greeting": (cfg.get("greeting") or "Hi! How can I help?").format(agent=a["name"], company=a["company"]),
        "quick_replies": cfg.get("quick_replies") or [],
        "brand": a["brand"],
        "consent_text": (a["settings"] or {}).get("consent_text")
        or f"Chats are handled by an AI assistant and may be reviewed by {a['company']} staff. Don't share passwords or card numbers.",
    }


@router.get("/widget.js")
async def widget_js() -> FileResponse:
    return FileResponse(BACKEND_DIR / "static" / "widget.js", media_type="application/javascript", headers={"Cache-Control": "public, max-age=300"})


@router.websocket("/ws/widget")
async def widget_socket(ws: WebSocket, key: str, visitor: str) -> None:
    if not VISITOR.match(visitor):
        await ws.close(code=4400)
        return
    try:
        a = await _agent_by_key(key)
    except HTTPException:
        await ws.close(code=4404)
        return
    await ws.accept()
    ip = ws.client.host if ws.client else "?"
    conv_id = None
    async with db.tx([a["tenant_id"]]) as c:
        conv = await c.fetchrow(
            """select v.id, v.state from conversations v join contacts k on k.id = v.contact_id
               where v.agent_id = $1 and k.channel = 'web' and k.channel_user_id = $2 and
                 (v.state <> 'RESOLVED' or v.last_message_at > now() - interval '12 hours')
               order by v.last_message_at desc limit 1""",
            a["id"],
            visitor,
        )
        history = []
        if conv:
            conv_id = conv["id"]
            history = db.rows(
                await c.fetch(
                    "select id, role, content, citations, created_at, conversation_id from messages where conversation_id = $1 order by created_at", conv_id
                )
            )
            for m in history:
                m["content"] = await conversations.detokenize(c, conv_id, m["content"])
    if conv_id:
        realtime.join(f"conv:{conv_id}", ws)
    await ws.send_json(
        {
            "type": "hello",
            "conversation_id": str(conv_id) if conv_id else None,
            "state": conv["state"] if conv else "BOT_ACTIVE",
            "history": [conversations.public_message(m) | {"id": str(m["id"]), "created_at": m["created_at"].isoformat()} for m in history],
        }
    )
    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") == "message":
                if rate_limited(f"widget:{visitor}", 20) or rate_limited(f"widget-ip:{ip}", 60):
                    await ws.send_json({"type": "error", "text": "You're sending messages too quickly. Please wait a moment."})
                    continue
                res = await conversations.inbound(a["tenant_id"], a["id"], "web", visitor, str(data.get("text", ""))[:2000], name=data.get("name"))
                if res.get("conversation_id") and str(res["conversation_id"]) != str(conv_id):
                    conv_id = res["conversation_id"]
                    realtime.join(f"conv:{conv_id}", ws)
                    if data.get("consent"):
                        async with db.tx([a["tenant_id"]]) as c:
                            await c.execute(
                                "update contacts set consent_at = coalesce(consent_at, now()) where tenant_id = $1 and channel = 'web' and channel_user_id = $2",
                                a["tenant_id"],
                                visitor,
                            )
                await ws.send_json({"type": "ack", "conversation_id": str(conv_id), "state": res.get("state")})
            elif data.get("type") == "csat" and conv_id and data.get("score") in (1, 5):
                async with db.tx([a["tenant_id"]]) as c:
                    await c.execute("update conversations set csat = $2 where id = $1", conv_id, int(data["score"]))
    except WebSocketDisconnect:
        pass
    except Exception:  # malformed frames: drop the socket, the widget reconnects
        await ws.close(code=4400)
    finally:
        realtime.leave(ws)


# ---------------------------------------------------------------- channel webhooks


async def _connection(cid: UUID, type_: str) -> dict[str, Any]:
    async with db.tx(system=True) as c:
        conn = db.row(await c.fetchrow("select * from channel_connections where id = $1 and type = $2 and status = 'active'", cid, type_))
    if not conn:
        raise HTTPException(404)
    return conn


@router.get("/webhooks/whatsapp/{cid}")
async def whatsapp_verify(
    cid: UUID, mode: str = Query(alias="hub.mode"), token: str = Query(alias="hub.verify_token"), challenge: str = Query(alias="hub.challenge")
) -> PlainTextResponse:
    conn = await _connection(cid, "whatsapp")
    if mode != "subscribe" or token != conn["webhook_secret"]:
        raise HTTPException(403, "Verify token mismatch")
    return PlainTextResponse(challenge)


@router.post("/webhooks/whatsapp/{cid}")
async def whatsapp_webhook(cid: UUID, request: Request) -> dict:
    conn = await _connection(cid, "whatsapp")
    body = await request.body()
    secrets = decrypt(conn["tenant_id"], conn["secrets_enc"])
    if not verify_meta_signature(secrets["app_secret"], body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "Bad signature")
    for m in channels.parse_whatsapp(await request.json()):
        if m["phone_number_id"] == conn["external_id"]:
            await conversations.inbound(
                conn["tenant_id"], conn["agent_id"], "whatsapp", m["from"], m["text"], name=m["name"], external_id=f"wa:{m['id']}", connection_id=conn["id"]
            )
    return {"ok": True}


@router.post("/webhooks/telegram/{cid}")
async def telegram_webhook(cid: UUID, request: Request) -> dict:
    conn = await _connection(cid, "telegram")
    if request.headers.get("x-telegram-bot-api-secret-token") != conn["webhook_secret"]:
        raise HTTPException(401, "Bad secret")
    await channels.handle_telegram_update(conn, await request.json())
    return {"ok": True}


# ---------------------------------------------------------------- REST API channel


class ApiMessage(BaseModel):
    agent_id: UUID
    user_id: str = Field(min_length=1, max_length=80, description="Your stable id for this end user")
    text: str = Field(min_length=1, max_length=4000)
    name: str | None = None


@router.post("/v1/messages", tags=["api-channel"])
async def api_message(body: ApiMessage, tenant_id: UUID = Depends(api_key_tenant)) -> dict:
    """Talk to an agent from any system. Returns the agent's reply synchronously."""
    if rate_limited(f"api:{tenant_id}", 120):
        raise HTTPException(429, "Rate limit: 120 messages/minute per workspace")
    async with db.tx([tenant_id]) as c:
        if not await c.fetchval("select 1 from agents where id = $1 and tenant_id = $2", body.agent_id, tenant_id):
            raise HTTPException(404, "Agent not found in this workspace")
    res = await conversations.inbound(tenant_id, body.agent_id, "api", body.user_id, body.text, name=body.name, auto_reply=False)
    if res.get("state") != "BOT_ACTIVE":
        return {
            "conversation_id": res.get("conversation_id"),
            "state": res.get("state"),
            "reply": None,
            "note": "A human agent is handling this conversation; poll GET /v1/conversations/{id}/messages for replies.",
        }
    turn = await conversations.reply_now(tenant_id, res["conversation_id"]) or {}
    return {
        "conversation_id": res["conversation_id"],
        "reply": turn.get("reply"),
        "citations": turn.get("citations"),
        "state": turn.get("state"),
        "handover": (turn.get("trace") or {}).get("handover"),
    }


@router.get("/v1/conversations/{cid}/messages", tags=["api-channel"])
async def api_messages(cid: UUID, tenant_id: UUID = Depends(api_key_tenant)) -> list[dict]:
    async with db.tx([tenant_id]) as c:
        rows = db.rows(
            await c.fetch(
                "select m.id, m.role, m.content, m.created_at, m.conversation_id from messages m join conversations v on v.id = m.conversation_id "
                "where v.id = $1 and v.tenant_id = $2 and v.channel = 'api' order by m.created_at",
                cid,
                tenant_id,
            )
        )
        for m in rows:
            m["content"] = await conversations.detokenize(c, cid, m["content"])
    return rows


@router.get("/public/templates")
async def public_templates() -> list[dict]:
    return templates.summary()
