"""Event-driven workflow engine on the job queue (Temporal in the target architecture; actions unchanged).

emit() records an analytics event and queues `workflow.event`; matching workflows create a run whose steps
execute one job each (`workflow.step`), so retries, delays and failures are per step and visible.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import asyncpg
from jinja2 import ChainableUndefined
from jinja2.sandbox import SandboxedEnvironment

from app import db, integrations, jobs

log = logging.getLogger("agentgrid.workflows")
_jinja = SandboxedEnvironment(undefined=ChainableUndefined, autoescape=False)
ACTIONS = [
    "crm.upsert_contact",
    "hubspot.upsert",
    "notify.email",
    "notify.slack",
    "webhook.post",
    "channel.send_message",
    "conversation.tag",
    "delay",
    "condition",
]
EVENTS = ["lead.updated", "lead.qualified", "appointment.booked", "appointment.cancelled", "conversation.escalated", "conversation.resolved"]


async def emit(
    c: asyncpg.Connection,
    tenant_id: UUID,
    type_: str,
    *,
    ids: dict[str, Any] | None = None,
    event: dict[str, Any] | None = None,
    agent_id: UUID | None = None,
    conversation_id: UUID | None = None,
    channel: str | None = None,
) -> None:
    ids = {k: str(v) for k, v in (ids or {}).items() if v}
    await c.execute(
        "insert into analytics_events (tenant_id, type, agent_id, conversation_id, channel, props) values ($1,$2,$3,$4,$5,$6)",
        tenant_id,
        type_,
        agent_id,
        conversation_id,
        channel,
        (event or {}) | ids,
    )
    await jobs.enqueue(c, "workflow.event", {"type": type_, "ids": ids, "event": event or {}}, tenant_id)


def _get(ctx: dict[str, Any], path: str) -> Any:
    cur: Any = ctx
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def _compare(op: str, left: Any, right: Any) -> bool:
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op in (">", ">=", "<", "<="):
        a, b = float(left), float(right)
        return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}[op]
    if op == "in":
        return left in (right or [])
    if op == "contains":
        return str(right).lower() in str(left or "").lower()
    if op == "exists":
        return left not in (None, "", [])
    raise KeyError(op)


def matches(ctx: dict[str, Any], filters: list[dict[str, Any]] | None) -> bool:
    """Whitelisted comparisons only (no eval): every filter must hold."""
    for f in filters or []:
        try:
            if not _compare(f.get("op", "=="), _get(ctx, f["field"]), f.get("value")):
                return False
        except (KeyError, TypeError, ValueError):
            return False
    return True


def render(value: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _jinja.from_string(value).render(**ctx).strip() if "{{" in value or "{%" in value else value
    if isinstance(value, dict):
        return {k: render(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, ctx) for v in value]
    return value


async def build_context(c: asyncpg.Connection, tenant_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
    """Fresh data at step time (a condition after a delay sees the lead's *current* stage)."""
    from app.conversations import detokenize

    ids = payload.get("ids", {})
    t = await c.fetchrow("select name, settings from tenants where id = $1", tenant_id)
    tz = ZoneInfo((t["settings"] or {}).get("timezone", "Asia/Kolkata"))
    ctx: dict[str, Any] = {
        "event": payload.get("event", {}),
        "type": payload.get("type"),
        "tenant": {"name": t["name"], "sales_email": (t["settings"] or {}).get("sales_email", "sales@example.com")},
    }
    if lid := ids.get("lead_id"):
        if lead := await c.fetchrow("select id, fields, score, stage, contact_id, conversation_id from leads where id = $1", UUID(lid)):
            ctx["lead"] = dict(lead)
            ids.setdefault("contact_id", str(lead["contact_id"]))
            if lead["conversation_id"]:
                ids.setdefault("conversation_id", str(lead["conversation_id"]))
    if aid := ids.get("appointment_id"):
        if a := await c.fetchrow("select * from appointments where id = $1", UUID(aid)):
            local = a["starts_at"].astimezone(tz)
            reminder = max(a["starts_at"] - timedelta(hours=24), datetime.now(UTC) + timedelta(minutes=1))
            ctx["appointment"] = dict(a) | {
                "when": local.strftime("%a %d %b %Y, %I:%M %p ") + local.tzname(),
                "reminder_at": reminder.isoformat(),
            }
            ids.setdefault("contact_id", str(a["contact_id"]) if a["contact_id"] else None)
            if a["conversation_id"]:
                ids.setdefault("conversation_id", str(a["conversation_id"]))
    if (cid := ids.get("contact_id")) and (ct := await c.fetchrow("select id, name, email, phone from contacts where id = $1", UUID(cid))):
        ctx["contact"] = dict(ct)
    if (vid := ids.get("conversation_id")) and (cv := await c.fetchrow("select id, channel, state from conversations where id = $1", UUID(vid))):
        ctx["conversation"] = dict(cv)
        if ctx.get("contact") and ctx["contact"].get("email", "") and "<EMAIL_" in ctx["contact"]["email"]:
            ctx["contact"]["email"] = await detokenize(c, cv["id"], ctx["contact"]["email"])
    return ctx


@jobs.handler("workflow.event")
async def on_event(payload: dict[str, Any], tenant_id: UUID | None) -> None:
    async with db.tx([tenant_id]) as c:
        flows = await c.fetch("select * from workflows where enabled and trigger->>'event' = $1", payload["type"])
        if not flows:
            return
        ctx = await build_context(c, tenant_id, payload)
        for wf in flows:
            if matches(ctx, wf["trigger"].get("filter")):
                run_id = await c.fetchval(
                    "insert into workflow_runs (tenant_id, workflow_id, event) values ($1, $2, $3) returning id", tenant_id, wf["id"], payload
                )
                await jobs.enqueue(c, "workflow.step", {"run_id": str(run_id), "index": 0}, tenant_id)


async def _execute(c: asyncpg.Connection, tenant_id: UUID, action: str, params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    secrets = await integrations.tenant_secrets(c, tenant_id)
    if action == "crm.upsert_contact" or action == "hubspot.upsert":
        lead, contact = ctx.get("lead") or {}, ctx.get("contact") or {}
        out: dict[str, Any] = {}
        if action == "crm.upsert_contact" and lead:
            await c.execute("update leads set crm_ids = crm_ids || jsonb_build_object('builtin', now()::text) where id = $1", lead["id"])
            out["builtin_crm"] = "synced"
        if token := secrets.get("hubspot_token"):
            fields = lead.get("fields", {})
            first, _, last = (fields.get("name") or contact.get("name") or "").partition(" ")
            out |= await integrations.hubspot_upsert(
                token,
                {
                    "email": fields.get("email") or contact.get("email"),
                    "firstname": first,
                    "lastname": last,
                    "phone": fields.get("phone") or contact.get("phone"),
                    "hs_lead_status": "NEW",
                },
            )
            if lead and out.get("hubspot") not in (None, "exists"):
                await c.execute("update leads set crm_ids = crm_ids || jsonb_build_object('hubspot', $2::text) where id = $1", lead["id"], out["hubspot"])
        elif action == "hubspot.upsert":
            out["hubspot"] = "skipped: HubSpot not connected"
        return out
    if action == "notify.email":
        to = params.get("to") or ""
        if "@" not in to:
            return {"skipped": "no recipient email"}
        ics = None
        if params.get("attach_ics") and (a := ctx.get("appointment")):
            ics = integrations.make_ics(f"{a['service']} - {ctx['tenant']['name']}", a["starts_at"], a["ends_at"], ctx["tenant"]["name"])
        return await integrations.send_email(c, tenant_id, to, params.get("subject", "(no subject)"), params.get("body", ""), ics)
    if action == "notify.slack":
        url = secrets.get("slack_webhook_url")
        return await integrations.slack(url, params.get("text", "")) if url else {"skipped": "Slack not connected"}
    if action == "webhook.post":
        return await integrations.post_webhook(params["url"], secrets.get("webhook_secret", ""), {"type": ctx.get("type"), "data": ctx})
    if action == "channel.send_message":
        from app.conversations import send_bot_message

        conv = ctx.get("conversation")
        if not conv:
            return {"skipped": "no conversation"}
        await send_bot_message(c, tenant_id, conv["id"], params.get("text", ""))
        return {"sent_to": conv["channel"]}
    if action == "conversation.tag":
        if conv := ctx.get("conversation"):
            await c.execute(
                "update conversations set tags = array(select distinct unnest(tags || $2::text[])) where id = $1", conv["id"], [params.get("tag", "tagged")]
            )
        return {"tag": params.get("tag")}
    if action == "delay":
        if until := params.get("until"):
            when = datetime.fromisoformat(str(until))
        else:
            when = datetime.now(UTC) + timedelta(minutes=float(params.get("minutes", 0)) + 60 * float(params.get("hours", 0)))
        return {"resume_at": max(when, datetime.now(UTC)).isoformat()}
    if action == "condition":
        return {"passed": matches(ctx, params.get("if"))}
    raise ValueError(f"unknown action {action}")


@jobs.handler("workflow.step")
async def on_step(payload: dict[str, Any], tenant_id: UUID | None) -> None:
    run_id, index = UUID(payload["run_id"]), int(payload["index"])
    async with db.tx([tenant_id]) as c:
        run = await c.fetchrow("select r.*, w.steps from workflow_runs r join workflows w on w.id = r.workflow_id where r.id = $1", run_id)
        if not run or run["status"] in ("succeeded", "stopped"):
            return
        steps = run["steps"]
        if index >= len(steps):
            await c.execute("update workflow_runs set status = 'succeeded', finished_at = now() where id = $1", run_id)
            return
        step = steps[index]
        ctx = await build_context(c, tenant_id, run["event"]) | {"outputs": run["outputs"]}
        params = render(step.get("params", {}), ctx)
    try:
        async with db.tx([tenant_id]) as c:
            output = await _execute(c, tenant_id, step["action"], params, ctx)
            await c.execute(
                """insert into workflow_step_runs (tenant_id, run_id, step_id, action, status, output)
                   values ($1,$2,$3,$4,'succeeded',$5)
                   on conflict (run_id, step_id) do update set status = 'succeeded', output = $5, error = null,
                     attempts = workflow_step_runs.attempts + 1""",
                tenant_id,
                run_id,
                step["id"],
                step["action"],
                output,
            )
            await c.execute(
                "update workflow_runs set status = 'running', error = null, outputs = outputs || jsonb_build_object($2::text, $3::jsonb) where id = $1",
                run_id,
                step["id"],
                output,
            )
            if step["action"] == "condition" and not output["passed"]:
                await c.execute("update workflow_runs set status = 'stopped', finished_at = now() where id = $1", run_id)
                return
            run_at = datetime.fromisoformat(output["resume_at"]) if step["action"] == "delay" else None
            await jobs.enqueue(c, "workflow.step", {"run_id": str(run_id), "index": index + 1}, tenant_id, run_at=run_at)
    except Exception as exc:
        async with db.tx([tenant_id]) as c:
            await c.execute(
                """insert into workflow_step_runs (tenant_id, run_id, step_id, action, status, error)
                   values ($1,$2,$3,$4,'failed',$5)
                   on conflict (run_id, step_id) do update set status = 'failed', error = $5, attempts = workflow_step_runs.attempts + 1""",
                tenant_id,
                run_id,
                step["id"],
                step["action"],
                str(exc)[:500],
            )
            await c.execute("update workflow_runs set status = 'failed', error = $2 where id = $1", run_id, f"{step['id']}: {exc}"[:500])
        raise
