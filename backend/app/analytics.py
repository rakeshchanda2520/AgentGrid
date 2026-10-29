"""KPI queries (plain SQL over operational tables; materialized views / ClickHouse in the target)."""

from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from app import db


def _num(v: Any) -> float | None:
    return round(float(v), 4) if v is not None else None


async def overview(c: asyncpg.Connection, tenants: list[UUID], start: datetime, end: datetime, agent_id: UUID | None = None) -> dict[str, Any]:
    args = [tenants, start, end, agent_id]
    conv_filter = "tenant_id = any($1) and started_at >= $2 and started_at < $3 and ($4::uuid is null or agent_id = $4)"
    k = db.row(
        await c.fetchrow(
            f"""
        select count(*) as conversations,
               count(*) filter (where escalated) as escalated,
               count(*) filter (where state = 'RESOLVED') as resolved,
               count(*) filter (where state = 'RESOLVED' and not human_replied) as auto_resolved,
               percentile_cont(0.5) within group (order by first_response_ms) as frt_p50,
               percentile_cont(0.95) within group (order by first_response_ms) as frt_p95,
               avg(csat) as csat, count(csat) as csat_count
        from conversations where {conv_filter}""",
            *args,
        )
    )
    leads = db.row(
        await c.fetchrow(
            f"""
        select count(*) filter (where stage <> 'new') as captured,
               count(*) filter (where stage in ('qualified', 'hot', 'booked')) as qualified,
               count(*) filter (where stage = 'booked') as booked
        from leads where conversation_id in (select id from conversations where {conv_filter})""",
            *args,
        )
    )
    appts = await c.fetchval(
        "select count(*) from appointments where tenant_id = any($1) and created_at >= $2 and created_at < $3 and ($4::uuid is null or agent_id = $4)", *args
    )
    msgs = db.row(
        await c.fetchrow(
            f"""
        select count(*) as messages,
               count(*) filter (where role = 'assistant') as ai_messages,
               percentile_cont(0.5) within group (order by latency_ms) filter (where role = 'assistant') as reply_p50,
               percentile_cont(0.95) within group (order by latency_ms) filter (where role = 'assistant') as reply_p95,
               coalesce(sum(cost_usd), 0) as cost, coalesce(sum(tokens_in), 0) as tokens_in, coalesce(sum(tokens_out), 0) as tokens_out
        from messages where conversation_id in (select id from conversations where {conv_filter})""",
            *args,
        )
    )
    series = db.rows(
        await c.fetch(
            f"""
        select date_trunc('day', started_at)::date as day, count(*) as conversations,
               count(*) filter (where escalated) as escalated,
               count(*) filter (where id in (select conversation_id from leads where stage in ('qualified','hot','booked'))) as qualified
        from conversations where {conv_filter} group by 1 order by 1""",
            *args,
        )
    )
    channels = db.rows(await c.fetch(f"select channel, count(*) as conversations from conversations where {conv_filter} group by 1 order by 2 desc", *args))
    agents = db.rows(
        await c.fetch(
            """
        select a.id, a.name, count(v.id) as conversations,
               count(v.id) filter (where v.escalated) as escalated,
               count(v.id) filter (where v.state = 'RESOLVED' and not v.human_replied) as auto_resolved,
               percentile_cont(0.5) within group (order by v.first_response_ms) as frt_p50
        from agents a left join conversations v on v.agent_id = a.id and v.started_at >= $2 and v.started_at < $3
        where a.tenant_id = any($1) and ($4::uuid is null or a.id = $4) group by a.id, a.name order by 3 desc""",
            *args,
        )
    )
    humans = db.rows(
        await c.fetch(
            f"""
        select u.name, count(distinct m.conversation_id) as conversations, count(*) as replies
        from messages m join users u on u.id = m.author_id
        where m.role = 'human' and m.conversation_id in (select id from conversations where {conv_filter})
        group by u.name order by 2 desc""",
            *args,
        )
    )
    usage = db.rows(
        await c.fetch(
            "select model, sum(messages) as messages, sum(tokens_in) as tokens_in, sum(tokens_out) as tokens_out, sum(cost_usd) as cost_usd "
            "from usage_daily where tenant_id = any($1) and day >= $2::date and day <= $3::date group by model order by 5 desc",
            tenants,
            start,
            end,
        )
    )
    total = k["conversations"] or 0
    resolved = k["resolved"] or 0
    return {
        "kpis": {
            "conversations": total,
            "messages": msgs["messages"],
            "ai_messages": msgs["ai_messages"],
            "automated_resolution_rate": _num(k["auto_resolved"] / resolved) if resolved else None,
            "escalation_rate": _num(k["escalated"] / total) if total else None,
            "first_response_p50_ms": _num(k["frt_p50"]),
            "first_response_p95_ms": _num(k["frt_p95"]),
            "reply_latency_p50_ms": _num(msgs["reply_p50"]),
            "reply_latency_p95_ms": _num(msgs["reply_p95"]),
            "leads_captured": leads["captured"],
            "leads_qualified": leads["qualified"],
            "appointments": appts,
            "lead_conversion_rate": _num(leads["qualified"] / leads["captured"]) if leads["captured"] else None,
            "booking_rate": _num(leads["booked"] / leads["qualified"]) if leads["qualified"] else None,
            "csat": _num(k["csat"]),
            "csat_responses": k["csat_count"],
            "llm_cost_usd": _num(msgs["cost"]),
            "tokens_in": msgs["tokens_in"],
            "tokens_out": msgs["tokens_out"],
        },
        "funnel": [
            {"stage": "Conversations", "value": total},
            {"stage": "Leads captured", "value": leads["captured"]},
            {"stage": "Qualified", "value": leads["qualified"]},
            {"stage": "Booked", "value": leads["booked"]},
        ],
        "series": series,
        "channels": channels,
        "agents": agents,
        "humans": humans,
        "usage": usage,
    }


async def agency_rollup(c: asyncpg.Connection, clients: list[UUID], start: datetime, end: datetime) -> list[dict[str, Any]]:
    return db.rows(
        await c.fetch(
            """
        select t.id, t.name, t.slug,
               count(distinct v.id) as conversations,
               count(distinct v.id) filter (where v.escalated) as escalated,
               count(distinct l.id) filter (where l.stage in ('qualified', 'hot', 'booked')) as qualified,
               count(distinct l.id) filter (where l.stage = 'booked') as booked,
               (select coalesce(sum(cost_usd), 0) from usage_daily u where u.tenant_id = t.id and u.day >= $2::date) as cost_usd,
               (select count(*) from agents a where a.tenant_id = t.id) as agents
        from tenants t
        left join conversations v on v.tenant_id = t.id and v.started_at >= $2 and v.started_at < $3
        left join leads l on l.conversation_id = v.id
        where t.id = any($1) group by t.id order by t.name""",
            clients,
            start,
            end,
        )
    )
