"""Conversation pipeline shared by every channel:

inbound() → store (PII-tokenized, deduped) → job `agent.reply` → run_turn() runs the LangGraph agent
(streaming tokens to the widget) → store reply + usage → deliver() to the customer's channel.
Human agents take over through claim / reply / return_to_bot / resolve.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import asyncpg
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from app import db, jobs, realtime
from app.agent import copilot
from app.agent.graph import build
from app.agent.guardrails import text_of
from app.agent.tools import Turn, make_tools
from app.llm import chat_model, cost_usd, specs_for_agent
from app.security import TOKEN_RE, decrypt, encrypt, find_pii, normalize_pii, sha256
from app.workflows import emit

log = logging.getLogger("agentgrid.conversations")
STREAM_CHANNELS = {"web", "playground"}


# ---------------------------------------------------------------- PII tokens


async def tokenize(c: asyncpg.Connection, tenant_id: UUID, conv_id: UUID, text: str) -> str:
    spans = find_pii(text)
    if not spans:
        return text
    existing = {r["value_hash"]: r["token"] for r in await c.fetch("select token, value_hash from pii_tokens where conversation_id = $1", conv_id)}
    counts: dict[str, int] = {}
    for tok in existing.values():
        kind = tok[1:].rsplit("_", 1)[0]
        counts[kind] = counts.get(kind, 0) + 1
    out, last = [], 0
    for start, end, kind, value in spans:
        h = sha256(f"{kind}:{normalize_pii(kind, value)}")
        token = existing.get(h)
        if not token:
            counts[kind] = counts.get(kind, 0) + 1
            token = f"<{kind}_{counts[kind]}>"
            await c.execute(
                "insert into pii_tokens (tenant_id, conversation_id, token, kind, value_enc, value_hash) values ($1,$2,$3,$4,$5,$6)",
                tenant_id,
                conv_id,
                token,
                kind,
                encrypt(tenant_id, value),
                h,
            )
            existing[h] = token
        out.append(text[last:start] + token)
        last = end
    return "".join(out) + text[last:]


async def detokenize(c: asyncpg.Connection, conv_id: UUID, text: str) -> str:
    if not text or "<" not in text or not TOKEN_RE.search(text):
        return text
    found = {
        r["token"]: decrypt(r["tenant_id"], r["value_enc"])
        for r in await c.fetch("select tenant_id, token, value_enc from pii_tokens where conversation_id = $1", conv_id)
    }
    return TOKEN_RE.sub(lambda m: found.get(m.group(0), m.group(0)), text)


# ---------------------------------------------------------------- inbound


async def open_conversation(
    c: asyncpg.Connection,
    tenant_id: UUID,
    agent_id: UUID,
    channel: str,
    user_ref: str,
    name: str | None = None,
    connection_id: UUID | None = None,
    simulated: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    contact = db.row(
        await c.fetchrow(
            """insert into contacts (tenant_id, channel, channel_user_id, name) values ($1,$2,$3,$4)
           on conflict (tenant_id, channel, channel_user_id) do update set name = coalesce(contacts.name, excluded.name)
           returning *""",
            tenant_id,
            channel,
            user_ref,
            name,
        )
    )
    conv = db.row(
        await c.fetchrow(
            "select * from conversations where agent_id = $1 and contact_id = $2 order by last_message_at desc limit 1",
            agent_id,
            contact["id"],
        )
    )
    created = False
    if not conv or (conv["state"] == "RESOLVED" and (datetime.now(UTC) - conv["last_message_at"]).total_seconds() > 12 * 3600):
        conv = db.row(
            await c.fetchrow(
                """insert into conversations (tenant_id, agent_id, contact_id, channel, connection_id, simulated)
               values ($1,$2,$3,$4,$5,$6) returning *""",
                tenant_id,
                agent_id,
                contact["id"],
                channel,
                connection_id,
                simulated,
            )
        )
        created = True
        await c.execute(
            "insert into analytics_events (tenant_id, type, agent_id, conversation_id, channel) values ($1,'conversation.started',$2,$3,$4)",
            tenant_id,
            agent_id,
            conv["id"],
            channel,
        )
    return conv, contact, created


def public_message(m: dict[str, Any], content: str | None = None) -> dict[str, Any]:
    return {
        "id": m["id"],
        "role": m["role"],
        "content": content if content is not None else m["content"],
        "citations": m.get("citations"),
        "created_at": m["created_at"],
    }


async def inbound(
    tenant_id: UUID,
    agent_id: UUID,
    channel: str,
    user_ref: str,
    text: str,
    *,
    name: str | None = None,
    external_id: str | None = None,
    connection_id: UUID | None = None,
    simulated: bool = False,
    auto_reply: bool = True,
) -> dict[str, Any]:
    """auto_reply=False: the caller runs run_turn itself (playground, REST API channel answer synchronously)."""
    text = (text or "").strip()[:4000]
    if not text:
        return {"ignored": True}
    async with db.tx([tenant_id]) as c:
        conv, _, _ = await open_conversation(c, tenant_id, agent_id, channel, user_ref, name, connection_id, simulated)
        tokenized = await tokenize(c, tenant_id, conv["id"], text)
        msg = db.row(
            await c.fetchrow(
                """insert into messages (tenant_id, conversation_id, role, content, external_id) values ($1,$2,'user',$3,$4)
               on conflict (tenant_id, external_id) where external_id is not null do nothing returning *""",
                tenant_id,
                conv["id"],
                tokenized,
                external_id,
            )
        )
        if msg is None:
            return {"duplicate": True, "conversation_id": conv["id"]}
        state = "BOT_ACTIVE" if conv["state"] == "RESOLVED" else conv["state"]
        await c.execute(
            "update conversations set last_message_at = now(), state = $2, resolved_at = case when $2 = 'BOT_ACTIVE' then null else resolved_at end where id = $1",
            conv["id"],
            state,
        )
        if state == "BOT_ACTIVE" and auto_reply:
            await jobs.enqueue(c, "agent.reply", {"conversation_id": str(conv["id"])}, tenant_id)
    event = {"type": "message", "conversation_id": conv["id"], "message": public_message(msg, text), "state": state}
    await realtime.publish(f"tenant:{tenant_id}", event)
    return {"conversation_id": conv["id"], "message_id": msg["id"], "state": state}


# ---------------------------------------------------------------- the agent turn


def _history(rows: list[dict[str, Any]]) -> list:
    out: list = []
    for m in rows:
        if m["role"] == "user":
            out.append(HumanMessage(m["content"]))
        elif m["role"] == "assistant":
            out.append(AIMessage(m["content"]))
        elif m["role"] == "human":
            out.append(AIMessage(f"(Team member) {m['content']}"))
    return out


@jobs.handler("agent.reply")
async def reply_job(payload: dict[str, Any], tenant_id: UUID | None) -> None:
    await run_turn(tenant_id, UUID(payload["conversation_id"]))


async def reply_now(tenant_id: UUID, conv_id: UUID) -> dict[str, Any] | None:
    """Synchronous turn (playground, API channel), serialized with queued jobs for the same conversation."""
    async with jobs._conv_locks[str(conv_id)]:
        return await run_turn(tenant_id, conv_id)


async def run_turn(tenant_id: UUID, conv_id: UUID) -> dict[str, Any] | None:
    started = time.monotonic()
    async with db.tx([tenant_id]) as c:
        conv = db.row(await c.fetchrow("select * from conversations where id = $1", conv_id))
        if not conv or conv["state"] != "BOT_ACTIVE":
            return None
        agent = db.row(await c.fetchrow("select * from agents where id = $1", conv["agent_id"]))
        tenant = db.row(await c.fetchrow("select id, name, settings from tenants where id = $1", tenant_id))
        contact = db.row(await c.fetchrow("select * from contacts where id = $1", conv["contact_id"]))
        lead = db.row(await c.fetchrow("select * from leads where conversation_id = $1", conv_id))
        history = list(
            reversed(
                db.rows(await c.fetch("select role, content, created_at from messages where conversation_id = $1 order by created_at desc limit 24", conv_id))
            )
        )
        main, cheap, fallback = await specs_for_agent(c, agent)
    if not history or history[-1]["role"] != "user":
        return None  # nothing new to answer (e.g. a duplicate job)
    tz = ZoneInfo((tenant["settings"] or {}).get("timezone", "Asia/Kolkata"))
    turn = Turn(
        tenant_id=tenant_id,
        tenant=tenant,
        agent=agent,
        conversation=conv,
        contact=contact,
        lead=lead,
        tz=tz,
        now=datetime.now(UTC),
        memory=dict(conv["memory"] or {}),
    )
    tools = make_tools(agent)
    bound = chat_model(main).bind_tools(tools)
    if fallback:
        bound = bound.with_fallbacks([chat_model(fallback).bind_tools(tools)])
    graph = build(bound, tools, (tenant["settings"] or {}).get("blocked_terms", []))
    inputs = _history(history)
    room = f"conv:{conv_id}"
    final: dict[str, Any] | None = None
    try:
        if conv["channel"] in STREAM_CHANNELS:
            await realtime.publish(room, {"type": "typing"})
        async for mode, chunk in graph.astream(
            {"messages": inputs}, {"configurable": {"turn": turn}, "recursion_limit": 16}, stream_mode=["messages", "values"]
        ):
            if mode == "values":
                final = chunk
            elif conv["channel"] in STREAM_CHANNELS:
                piece, meta = chunk
                if meta.get("langgraph_node") == "agent" and isinstance(piece, AIMessageChunk) and (t := text_of(piece)):
                    await realtime.publish(room, {"type": "token", "text": t})
    except Exception:
        log.exception("agent turn failed for %s", conv_id)
        turn.handover_reason = turn.handover_reason or "assistant error"
        final = {"messages": [*inputs, AIMessage("Sorry, I ran into a problem. I'm passing you to our team so you're not kept waiting.")]}
    new = (final or {"messages": inputs})["messages"][len(inputs) :]
    replies = [text_of(m) for m in new if isinstance(m, AIMessage) and not m.tool_calls and text_of(m).strip()]
    reply = "\n\n".join(replies) or "Sorry, could you say that another way?"
    usage = [m.usage_metadata for m in new if isinstance(m, AIMessage) and getattr(m, "usage_metadata", None)]
    t_in = sum(u.get("input_tokens", 0) for u in usage)
    t_out = sum(u.get("output_tokens", 0) for u in usage)
    t_cached = sum((u.get("input_token_details") or {}).get("cache_read", 0) or 0 for u in usage)
    tool_calls = [{"name": tc["name"], "args": tc["args"]} for m in new if isinstance(m, AIMessage) for tc in (m.tool_calls or [])]
    tool_results = [{"name": m.name, "result": str(m.content)[:600]} for m in new if isinstance(m, ToolMessage)]
    latency = int((time.monotonic() - started) * 1000)
    cost = cost_usd(main, t_in, t_out)
    trace = {
        "path": turn.path,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "retrieved": turn.retrieved,
        "model": main.label,
        "handover": turn.handover_reason,
        "lead": {k: (turn.lead or {}).get(k) for k in ("score", "stage", "fields")},
    }
    async with db.tx([tenant_id]) as c:
        msg = db.row(
            await c.fetchrow(
                """insert into messages (tenant_id, conversation_id, role, content, citations, trace, provider, model, tokens_in, tokens_out,
                                     tokens_cached, cost_usd, latency_ms)
               values ($1,$2,'assistant',$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) returning *""",
                tenant_id,
                conv_id,
                reply,
                turn.citations,
                trace,
                main.provider_name,
                main.label,
                t_in,
                t_out,
                t_cached,
                cost,
                latency,
            )
        )
        first_user = next(m["created_at"] for m in history if m["role"] == "user")
        await c.execute(
            """update conversations set memory = $2, low_conf_turns = $3, last_message_at = now(),
               first_response_ms = coalesce(first_response_ms, $4) where id = $1""",
            conv_id,
            turn.memory,
            turn.conversation["low_conf_turns"],
            int((datetime.now(UTC) - first_user).total_seconds() * 1000),
        )
        await c.execute(
            """insert into usage_daily (tenant_id, day, model, messages, tokens_in, tokens_out, cost_usd) values ($1, current_date, $2, 1, $3, $4, $5)
               on conflict (tenant_id, day, model) do update set messages = usage_daily.messages + 1,
                 tokens_in = usage_daily.tokens_in + $3, tokens_out = usage_daily.tokens_out + $4, cost_usd = usage_daily.cost_usd + $5""",
            tenant_id,
            main.label,
            t_in,
            t_out,
            cost or 0,
        )
        await c.execute(
            "insert into analytics_events (tenant_id, type, agent_id, conversation_id, channel, props) values ($1,'message.answered',$2,$3,$4,$5)",
            tenant_id,
            agent["id"],
            conv_id,
            conv["channel"],
            {"latency_ms": latency, "cited": bool(turn.citations), "low_conf": turn.low_conf},
        )
        if turn.handover_reason:
            await c.execute("update conversations set state = 'PENDING_HUMAN', escalated = true where id = $1", conv_id)
            conv["state"] = "PENDING_HUMAN"
            await emit(
                c,
                tenant_id,
                "conversation.escalated",
                ids={"conversation_id": conv_id, "lead_id": (turn.lead or {}).get("id")},
                event={"reason": turn.handover_reason},
                agent_id=agent["id"],
                conversation_id=conv_id,
                channel=conv["channel"],
            )
        real = await detokenize(c, conv_id, reply)
        await deliver(c, tenant_id, conv, msg, real)
    if turn.handover_reason:
        msgs = history + [{"role": "assistant", "content": reply}]
        summary = await copilot.summarize(cheap, msgs, turn.lead, turn.handover_reason)
        async with db.tx([tenant_id]) as c:
            await c.execute("update conversations set summary = $2 where id = $1", conv_id, summary)
        await realtime.publish(f"tenant:{tenant_id}", {"type": "conversation", "conversation_id": conv_id, "state": "PENDING_HUMAN", "summary": summary})
    return {
        "reply": real,
        "message": msg,
        "trace": trace,
        "citations": turn.citations,
        "state": conv["state"],
        "usage": {"tokens_in": t_in, "tokens_out": t_out, "tokens_cached": t_cached, "cost_usd": cost, "latency_ms": latency},
    }


# ---------------------------------------------------------------- delivery & human side


async def deliver(c: asyncpg.Connection, tenant_id: UUID, conv: dict[str, Any], msg: dict[str, Any], real_text: str) -> None:
    event = {"type": "message", "conversation_id": conv["id"], "message": public_message(msg, real_text), "state": conv["state"]}
    await realtime.publish(f"conv:{conv['id']}", event)
    await realtime.publish(f"tenant:{tenant_id}", event)
    if conv["channel"] in ("whatsapp", "telegram") and not conv["simulated"]:
        await jobs.enqueue(c, "channel.send", {"conversation_id": str(conv["id"]), "text": real_text}, tenant_id, max_attempts=4)


async def send_bot_message(c: asyncpg.Connection, tenant_id: UUID, conv_id: UUID, text: str) -> None:
    """Proactive message from a workflow (follow-up nudge, reminder)."""
    conv = db.row(await c.fetchrow("select * from conversations where id = $1", conv_id))
    if not conv:
        return
    msg = db.row(
        await c.fetchrow(
            "insert into messages (tenant_id, conversation_id, role, content) values ($1,$2,'assistant',$3) returning *",
            tenant_id,
            conv_id,
            await tokenize(c, tenant_id, conv_id, text),
        )
    )
    await deliver(c, tenant_id, conv, msg, text)


async def human_reply(tenant_id: UUID, allowed: set[UUID], conv_id: UUID, user_id: UUID, text: str) -> dict[str, Any]:
    async with db.tx(allowed) as c:
        conv = db.row(await c.fetchrow("select * from conversations where id = $1 and tenant_id = $2", conv_id, tenant_id))
        if not conv:
            raise LookupError("conversation not found")
        msg = db.row(
            await c.fetchrow(
                "insert into messages (tenant_id, conversation_id, role, content, author_id) values ($1,$2,'human',$3,$4) returning *",
                tenant_id,
                conv_id,
                await tokenize(c, tenant_id, conv_id, text),
                user_id,
            )
        )
        await c.execute(
            """update conversations set state = 'HUMAN_ACTIVE', human_replied = true, assigned_user_id = coalesce(assigned_user_id, $2),
               last_message_at = now() where id = $1""",
            conv_id,
            user_id,
        )
        conv["state"] = "HUMAN_ACTIVE"
        await deliver(c, tenant_id, conv, msg, text)
    return public_message(msg, text)


async def set_state(tenant_id: UUID, allowed: set[UUID], conv_id: UUID, action: str, user_id: UUID) -> dict[str, Any]:
    async with db.tx(allowed) as c:
        conv = db.row(await c.fetchrow("select * from conversations where id = $1 and tenant_id = $2", conv_id, tenant_id))
        if not conv:
            raise LookupError("conversation not found")
        if action == "claim":
            await c.execute("update conversations set state = 'HUMAN_ACTIVE', assigned_user_id = $2 where id = $1", conv_id, user_id)
            state = "HUMAN_ACTIVE"
        elif action == "return-to-bot":
            await c.execute("update conversations set state = 'BOT_ACTIVE', low_conf_turns = 0 where id = $1", conv_id)
            state = "BOT_ACTIVE"
        elif action == "resolve":
            await c.execute("update conversations set state = 'RESOLVED', resolved_at = now(), outcome = coalesce(outcome, 'resolved') where id = $1", conv_id)
            state = "RESOLVED"
            await emit(
                c,
                tenant_id,
                "conversation.resolved",
                ids={"conversation_id": conv_id},
                event={"automated": not conv["human_replied"], "outcome": "resolved"},
                agent_id=conv["agent_id"],
                conversation_id=conv_id,
                channel=conv["channel"],
            )
        else:
            raise ValueError(action)
    event = {"type": "conversation", "conversation_id": conv_id, "state": state}
    await realtime.publish(f"tenant:{tenant_id}", event)
    await realtime.publish(f"conv:{conv_id}", {"type": "state", "state": state})
    return event


async def maintenance() -> None:
    """Auto-resolve idle bot conversations (counts toward automated resolution) and purge expired PII tokens."""
    async with db.tx(system=True) as c:
        idle = await c.fetch(
            """update conversations set state = 'RESOLVED', resolved_at = now(), outcome = coalesce(outcome, 'idle')
               where state = 'BOT_ACTIVE' and last_message_at < now() - interval '30 minutes' and not simulated
               returning id, tenant_id, agent_id, channel, human_replied"""
        )
        for r in idle:
            await emit(
                c,
                r["tenant_id"],
                "conversation.resolved",
                ids={"conversation_id": r["id"]},
                event={"automated": not r["human_replied"], "outcome": "idle"},
                agent_id=r["agent_id"],
                conversation_id=r["id"],
                channel=r["channel"],
            )
        await c.execute(
            """delete from pii_tokens p using tenants t where t.id = p.tenant_id
               and p.created_at < now() - make_interval(days => coalesce((t.settings->>'retention_days')::int, 90))"""
        )
