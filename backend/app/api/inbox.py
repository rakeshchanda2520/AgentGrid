"""Human-agent inbox, leads, appointments, contacts (GDPR), channel simulator, and the inbox WebSocket."""

import csv
import io
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import conversations, db, realtime
from app.agent import copilot
from app.auth import Principal, audit, load_access, require, role_on
from app.llm import specs_for_agent
from app.security import decode_access

router = APIRouter(tags=["inbox"])


async def _detok_all(c, items: list[dict[str, Any]], key: str = "content") -> None:
    for m in items:
        if m.get(key) and m.get("conversation_id"):
            m[key] = await conversations.detokenize(c, m["conversation_id"], m[key])


@router.get("/conversations")
async def list_conversations(
    state: str | None = None,
    channel: str | None = None,
    agent_id: UUID | None = None,
    mine: bool = False,
    limit: int = Query(60, le=200),
    p: Principal = Depends(require("inbox")),
) -> list[dict]:
    async with p.tx() as c:
        rows = db.rows(
            await c.fetch(
                """select v.id, v.agent_id, a.name as agent_name, v.channel, v.state, v.started_at, v.last_message_at, v.escalated,
                      v.assigned_user_id, v.simulated, v.tags, v.summary, k.name as contact_name, k.channel_user_id,
                      l.score as lead_score, l.stage as lead_stage,
                      (select content from messages m where m.conversation_id = v.id order by created_at desc limit 1) as preview,
                      v.id as conversation_id
               from conversations v join agents a on a.id = v.agent_id join contacts k on k.id = v.contact_id
               left join leads l on l.conversation_id = v.id
               where v.tenant_id = $1 and ($2::text is null or v.state = $2) and ($3::text is null or v.channel = $3)
                 and ($4::uuid is null or v.agent_id = $4) and (not $5 or v.assigned_user_id = $6)
                 and v.channel <> 'playground'
               order by case when v.state = 'PENDING_HUMAN' then 0 else 1 end, v.last_message_at desc limit $7""",
                p.active,
                state,
                channel,
                agent_id,
                mine,
                p.id,
                limit,
            )
        )
        await _detok_all(c, rows, "preview")
    return rows


@router.get("/conversations/{cid}")
async def get_conversation(cid: UUID, p: Principal = Depends(require("inbox"))) -> dict:
    async with p.tx() as c:
        conv = db.row(
            await c.fetchrow(
                """select v.*, a.name as agent_name, u.name as assigned_name from conversations v join agents a on a.id = v.agent_id
               left join users u on u.id = v.assigned_user_id where v.id = $1 and v.tenant_id = $2""",
                cid,
                p.active,
            )
        )
        if not conv:
            raise HTTPException(404)
        msgs = db.rows(
            await c.fetch(
                """select m.id, m.conversation_id, m.role, m.content, m.citations, m.trace, m.model, m.tokens_in, m.tokens_out, m.cost_usd,
                      m.latency_ms, m.created_at, u.name as author_name
               from messages m left join users u on u.id = m.author_id where m.conversation_id = $1 order by m.created_at""",
                cid,
            )
        )
        await _detok_all(c, msgs)
        contact = db.row(await c.fetchrow("select * from contacts where id = $1", conv["contact_id"]))
        lead = db.row(await c.fetchrow("select * from leads where conversation_id = $1", cid))
        appts = db.rows(await c.fetch("select * from appointments where conversation_id = $1 order by starts_at", cid))
    return conv | {"messages": msgs, "contact": contact, "lead": lead, "appointments": appts}


class Reply(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.post("/conversations/{cid}/reply")
async def reply(cid: UUID, body: Reply, p: Principal = Depends(require("inbox"))) -> dict:
    try:
        return await conversations.human_reply(p.active, p.allowed, cid, p.id, body.text)
    except LookupError:
        raise HTTPException(404) from None


@router.post("/conversations/{cid}/{action}")
async def change_state(cid: UUID, action: str, p: Principal = Depends(require("inbox"))) -> dict:
    if action not in ("claim", "return-to-bot", "resolve"):
        raise HTTPException(404)
    try:
        out = await conversations.set_state(p.active, p.allowed, cid, action, p.id)
    except LookupError:
        raise HTTPException(404) from None
    async with p.tx() as c:
        await audit(c, p.active, p.id, f"conversation.{action}", str(cid))
    return out


@router.get("/conversations/{cid}/suggestions")
async def suggestions(cid: UUID, p: Principal = Depends(require("inbox"))) -> dict:
    async with p.tx() as c:
        conv = await c.fetchrow("select agent_id from conversations where id = $1 and tenant_id = $2", cid, p.active)
        if not conv:
            raise HTTPException(404)
        agent = db.row(await c.fetchrow("select * from agents where id = $1", conv["agent_id"]))
        _, cheap, _ = await specs_for_agent(c, agent)
        msgs = db.rows(await c.fetch("select role, content from messages where conversation_id = $1 order by created_at", cid))
    return {"replies": await copilot.suggest(cheap, msgs)}


# ---------------------------------------------------------------- leads & appointments


@router.get("/leads")
async def list_leads(stage: str | None = None, q: str | None = None, p: Principal = Depends(require("leads"))) -> list[dict]:
    async with p.tx() as c:
        return db.rows(
            await c.fetch(
                """select l.*, k.name as contact_name, k.phone, k.email, a.name as agent_name, v.channel
               from leads l join contacts k on k.id = l.contact_id join agents a on a.id = l.agent_id
               left join conversations v on v.id = l.conversation_id
               where l.tenant_id = $1 and ($2::text is null or l.stage = $2)
                 and ($3::text is null or k.name ilike '%' || $3 || '%' or l.fields::text ilike '%' || $3 || '%')
               order by l.updated_at desc limit 300""",
                p.active,
                stage,
                q,
            )
        )


class LeadUpdate(BaseModel):
    stage: str | None = Field(None, pattern="^(new|engaged|qualified|hot|booked|won|lost)$")
    notes: str | None = None


@router.patch("/leads/{lid}")
async def update_lead(lid: UUID, body: LeadUpdate, p: Principal = Depends(require("leads"))) -> dict:
    async with p.tx() as c:
        row = db.row(
            await c.fetchrow(
                "update leads set stage = coalesce($3, stage), notes = coalesce($4, notes), updated_at = now() where id = $1 and tenant_id = $2 returning *",
                lid,
                p.active,
                body.stage,
                body.notes,
            )
        )
        if not row:
            raise HTTPException(404)
        await audit(c, p.active, p.id, "lead.updated", str(lid), body.model_dump(exclude_none=True))
    return row


@router.get("/leads/export.csv")
async def export_leads(p: Principal = Depends(require("leads"))) -> StreamingResponse:
    rows = await list_leads(None, None, p)
    keys = sorted({k for r in rows for k in r["fields"]})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "phone", "email", "score", "stage", "agent", "channel", "updated_at", *keys])
    for r in rows:
        w.writerow(
            [
                r["contact_name"],
                r["phone"],
                r["email"],
                r["score"],
                r["stage"],
                r["agent_name"],
                r["channel"],
                r["updated_at"],
                *[r["fields"].get(k, "") for k in keys],
            ]
        )
    async with p.tx() as c:
        await audit(c, p.active, p.id, "leads.exported", f"{len(rows)} rows")
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=leads.csv"})


@router.get("/appointments")
async def list_appointments(p: Principal = Depends(require("leads"))) -> list[dict]:
    async with p.tx() as c:
        return db.rows(
            await c.fetch(
                """select ap.*, a.name as agent_name from appointments ap join agents a on a.id = ap.agent_id
               where ap.tenant_id = $1 and ap.starts_at > now() - interval '14 days' order by ap.starts_at limit 300""",
                p.active,
            )
        )


class ApptUpdate(BaseModel):
    status: str = Field(pattern="^(booked|cancelled|completed)$")


@router.patch("/appointments/{aid}")
async def update_appointment(aid: UUID, body: ApptUpdate, p: Principal = Depends(require("leads"))) -> dict:
    async with p.tx() as c:
        row = db.row(await c.fetchrow("update appointments set status = $3 where id = $1 and tenant_id = $2 returning *", aid, p.active, body.status))
        if not row:
            raise HTTPException(404)
        await audit(c, p.active, p.id, "appointment.updated", str(aid), {"status": body.status})
    return row


# ---------------------------------------------------------------- GDPR


@router.get("/contacts/{kid}/export")
async def export_contact(kid: UUID, p: Principal = Depends(require("users"))) -> dict:
    async with p.tx() as c:
        contact = db.row(await c.fetchrow("select * from contacts where id = $1 and tenant_id = $2", kid, p.active))
        if not contact:
            raise HTTPException(404)
        msgs = db.rows(
            await c.fetch(
                "select m.conversation_id, m.role, m.content, m.created_at from messages m join conversations v on v.id = m.conversation_id "
                "where v.contact_id = $1 order by m.created_at",
                kid,
            )
        )
        await _detok_all(c, msgs)
        leads = db.rows(await c.fetch("select fields, score, stage, created_at from leads where contact_id = $1", kid))
        appts = db.rows(await c.fetch("select service, starts_at, status from appointments where contact_id = $1", kid))
        await audit(c, p.active, p.id, "contact.exported", str(kid))
    return {"contact": contact, "messages": msgs, "leads": leads, "appointments": appts}


@router.delete("/contacts/{kid}")
async def erase_contact(kid: UUID, p: Principal = Depends(require("users"))) -> dict:
    async with p.tx() as c:
        n = await c.execute("delete from contacts where id = $1 and tenant_id = $2", kid, p.active)
        await audit(c, p.active, p.id, "contact.erased", str(kid))
    return {"erased": n.endswith("1")}


# ---------------------------------------------------------------- simulator


class Simulated(BaseModel):
    agent_id: UUID
    user_id: str = Field(min_length=3, max_length=40)
    name: str = "Demo customer"
    text: str = Field(min_length=1, max_length=2000)


@router.post("/simulator/{channel}")
async def simulate(channel: str, body: Simulated, p: Principal = Depends(require("inbox"))) -> dict:
    """Runs a message through the real WhatsApp/Telegram pipeline (minus the network hop). Replies arrive on the inbox socket."""
    if channel not in ("whatsapp", "telegram"):
        raise HTTPException(404)
    async with p.tx() as c:
        if not await c.fetchval("select 1 from agents where id = $1 and tenant_id = $2", body.agent_id, p.active):
            raise HTTPException(404, "Agent not found")
    return await conversations.inbound(p.active, body.agent_id, channel, f"sim-{body.user_id}", body.text, name=body.name, simulated=True)


# ---------------------------------------------------------------- live updates


@router.websocket("/ws/inbox")
async def inbox_socket(ws: WebSocket, token: str, tenant: UUID) -> None:
    uid = decode_access(token)
    access = await load_access(uid) if uid else None
    t = next((t for t in (access[1] if access else []) if t["id"] == tenant), None)
    if not t or not role_on(access[0], access[2], t):
        await ws.close(code=4401)
        return
    await ws.accept()
    realtime.join(f"tenant:{tenant}", ws)
    try:
        while True:
            await ws.receive_text()  # keep-alive pings from the console
    except WebSocketDisconnect:
        pass
    finally:
        realtime.leave(ws)
