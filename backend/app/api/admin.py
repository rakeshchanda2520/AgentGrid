"""Workspaces (agency → clients), white-label branding, users, API keys, integrations, audit, outbox, jobs."""

import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import db, jobs, templates
from app.auth import Principal, audit, require
from app.security import decrypt, encrypt, hash_password, new_secret, sha256

router = APIRouter(tags=["admin"])


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "workspace"


async def create_agent(
    c, tenant_id: UUID, name: str, template_key: str, persona: str | None = None, public_key: str | None = None, business_profile: str = ""
) -> dict[str, Any]:
    t = templates.get(template_key)
    cfg = templates.agent_config(template_key) | {"business_profile": business_profile}
    agent = db.row(
        await c.fetchrow(
            """insert into agents (tenant_id, name, template_key, public_key, persona, config)
           values ($1,$2,$3,$4,$5,$6) returning *""",
            tenant_id,
            name,
            template_key,
            public_key or new_secret("pk_", 12),
            persona or t["persona"],
            cfg,
        )
    )
    for wf in t.get("workflows", []):
        await c.execute(
            "insert into workflows (tenant_id, name, trigger, steps) values ($1,$2,$3,$4)", tenant_id, f"{name}: {wf['name']}", wf["trigger"], wf["steps"]
        )
    return agent


# ---------------------------------------------------------------- workspaces


class NewClient(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    template_key: str | None = None
    agent_name: str | None = None
    timezone: str = "Asia/Kolkata"
    sales_email: str | None = None


@router.get("/tenants")
async def list_tenants(p: Principal = Depends(require("analytics"))) -> list[dict]:
    return p.tenants


@router.post("/tenants")
async def create_client(body: NewClient, p: Principal = Depends(require("clients"))) -> dict:
    by_id = {t["id"]: t for t in p.tenants}
    active = by_id[p.active]
    agency_id = active["id"] if active["kind"] == "agency" else active["parent_id"]
    if not agency_id or by_id.get(agency_id, {}).get("kind") != "agency":
        raise HTTPException(400, "Switch to an agency workspace to create clients")
    async with db.tx(system=True) as c:
        slug = _slug(body.name)
        if await c.fetchval("select 1 from tenants where slug = $1", slug):
            slug = f"{slug}-{new_secret(n=3).lower()[:4]}"
        tenant = db.row(
            await c.fetchrow(
                "insert into tenants (parent_id, kind, name, slug, settings) values ($1,'client',$2,$3,$4) returning id, parent_id, kind, name, slug, branding",
                agency_id,
                body.name,
                slug,
                {"timezone": body.timezone, "sales_email": body.sales_email or p.user["email"], "retention_days": 90},
            )
        )
        agent = None
        if body.template_key:
            agent = await create_agent(c, tenant["id"], body.agent_name or "Assistant", body.template_key)
        await audit(c, tenant["id"], p.id, "tenant.created", body.name)
    return tenant | {"agent": agent}


class TenantUpdate(BaseModel):
    name: str | None = None
    settings: dict[str, Any] | None = None


@router.get("/tenants/{tid}")
async def get_tenant(tid: UUID, p: Principal = Depends(require("analytics"))) -> dict:
    if tid not in p.allowed:
        raise HTTPException(404)
    async with db.tx(system=True) as c:
        t = db.row(await c.fetchrow("select id, parent_id, kind, name, slug, plan, settings, branding, secrets_enc from tenants where id = $1", tid))
    secrets = decrypt(tid, t.pop("secrets_enc")) or {}
    return t | {"integrations": {k: bool(v) for k, v in secrets.items()}}


@router.patch("/tenants/{tid}")
async def update_tenant(tid: UUID, body: TenantUpdate, p: Principal = Depends(require("users"))) -> dict:
    if tid not in p.allowed:
        raise HTTPException(404)
    allowed_settings = {"timezone", "sales_email", "retention_days", "blocked_terms", "monthly_message_quota", "consent_text"}
    async with db.tx(system=True) as c:
        if body.name:
            await c.execute("update tenants set name = $2 where id = $1", tid, body.name)
        if body.settings:
            clean = {k: v for k, v in body.settings.items() if k in allowed_settings}
            await c.execute("update tenants set settings = settings || $2 where id = $1", tid, clean)
        await audit(c, tid, p.id, "tenant.updated", meta=body.model_dump(exclude_none=True))
    return {"ok": True}


class Integrations(BaseModel):
    hubspot_token: str | None = None
    slack_webhook_url: str | None = None
    webhook_secret: str | None = None


@router.put("/tenants/{tid}/integrations")
async def set_integrations(tid: UUID, body: Integrations, p: Principal = Depends(require("workflows"))) -> dict:
    if tid not in p.allowed:
        raise HTTPException(404)
    async with db.tx(system=True) as c:
        current = decrypt(tid, await c.fetchval("select secrets_enc from tenants where id = $1", tid)) or {}
        for k, v in body.model_dump().items():
            if v is not None:
                current[k] = v.strip() or None
        current = {k: v for k, v in current.items() if v}
        await c.execute("update tenants set secrets_enc = $2 where id = $1", tid, encrypt(tid, current))
        await audit(c, tid, p.id, "integrations.updated", meta={k: True for k in current})
    return {k: True for k in current}


class Branding(BaseModel):
    product_name: str | None = None
    logo_url: str | None = None
    primary_color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    accent_color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    support_email: str | None = None
    hide_powered_by: bool | None = None
    widget_title: str | None = None


@router.patch("/tenants/{tid}/branding")
async def set_branding(tid: UUID, body: Branding, p: Principal = Depends(require("branding"))) -> dict:
    if tid not in p.allowed:
        raise HTTPException(404)
    async with db.tx(system=True) as c:
        b = await c.fetchval("update tenants set branding = branding || $2 where id = $1 returning branding", tid, body.model_dump(exclude_none=True))
        await audit(c, tid, p.id, "branding.updated", meta=body.model_dump(exclude_none=True))
    return b


# ---------------------------------------------------------------- users & keys


class NewUser(BaseModel):
    email: str
    name: str
    role: str = Field(pattern="^(agency_admin|client_admin|human_agent|viewer)$")


@router.get("/users")
async def list_users(p: Principal = Depends(require("users"))) -> list[dict]:
    async with db.tx(system=True) as c:
        return db.rows(
            await c.fetch(
                """select u.id, u.email, u.name, m.role, m.tenant_id from memberships m join users u on u.id = m.user_id
               where m.tenant_id = $1 order by u.name""",
                p.active,
            )
        )


@router.post("/users")
async def add_user(body: NewUser, p: Principal = Depends(require("users"))) -> dict:
    if body.role == "agency_admin" and p.role not in ("agency_admin", "platform_admin"):
        raise HTTPException(403, "Only agency admins can add agency admins")
    temp = None
    async with db.tx(system=True) as c:
        uid = await c.fetchval("select id from users where lower(email) = lower($1)", body.email)
        if not uid:
            temp = new_secret(n=9)
            uid = await c.fetchval(
                "insert into users (email, name, password_hash) values ($1,$2,$3) returning id", body.email.lower(), body.name, hash_password(temp)
            )
        await c.execute(
            "insert into memberships (user_id, tenant_id, role) values ($1,$2,$3) on conflict (user_id, tenant_id) do update set role = $3",
            uid,
            p.active,
            body.role,
        )
        await audit(c, p.active, p.id, "user.added", body.email, {"role": body.role})
    return {"id": uid, "temporary_password": temp}


@router.delete("/users/{uid}")
async def remove_user(uid: UUID, p: Principal = Depends(require("users"))) -> dict:
    if uid == p.id:
        raise HTTPException(400, "You cannot remove yourself")
    async with db.tx(system=True) as c:
        await c.execute("delete from memberships where user_id = $1 and tenant_id = $2", uid, p.active)
        await audit(c, p.active, p.id, "user.removed", str(uid))
    return {"ok": True}


@router.get("/api-keys")
async def list_keys(p: Principal = Depends(require("agents"))) -> list[dict]:
    async with p.tx() as c:
        return db.rows(
            await c.fetch("select id, name, prefix, created_at, last_used_at, revoked_at from api_keys where tenant_id = $1 order by created_at desc", p.active)
        )


class NewKey(BaseModel):
    name: str


@router.post("/api-keys")
async def create_key(body: NewKey, p: Principal = Depends(require("agents"))) -> dict:
    key = new_secret("ag_", 24)
    async with p.tx() as c:
        kid = await c.fetchval(
            "insert into api_keys (tenant_id, name, prefix, key_hash) values ($1,$2,$3,$4) returning id", p.active, body.name, key[:8], sha256(key)
        )
        await audit(c, p.active, p.id, "api_key.created", body.name)
    return {"id": kid, "key": key, "note": "Shown once. Store it safely."}


@router.delete("/api-keys/{kid}")
async def revoke_key(kid: UUID, p: Principal = Depends(require("agents"))) -> dict:
    async with p.tx() as c:
        await c.execute("update api_keys set revoked_at = now() where id = $1 and tenant_id = $2", kid, p.active)
        await audit(c, p.active, p.id, "api_key.revoked", str(kid))
    return {"ok": True}


# ---------------------------------------------------------------- audit, outbox, jobs


@router.get("/audit-logs")
async def audit_logs(p: Principal = Depends(require("audit"))) -> list[dict]:
    async with p.tx() as c:
        return db.rows(
            await c.fetch(
                """select a.ts, a.action, a.target, a.meta, a.ip, u.name as user_name from audit_logs a
               left join users u on u.id = a.user_id where a.tenant_id = $1 order by a.ts desc limit 200""",
                p.active,
            )
        )


@router.get("/outbox")
async def outbox(p: Principal = Depends(require("workflows"))) -> list[dict]:
    async with p.tx() as c:
        return db.rows(
            await c.fetch(
                "select id, to_addr, subject, body, ics is not null as has_invite, status, error, created_at from outbox_emails "
                "where tenant_id = $1 order by created_at desc limit 100",
                p.active,
            )
        )


@router.get("/jobs")
async def list_jobs(status: str = "dead", p: Principal = Depends(require("workflows"))) -> list[dict]:
    async with db.tx(system=True) as c:
        return db.rows(
            await c.fetch(
                "select id, kind, payload, status, attempts, last_error, run_at, created_at from jobs where tenant_id = $1 and status = $2 "
                "order by id desc limit 100",
                p.active,
                status,
            )
        )


@router.post("/jobs/{jid}/retry")
async def retry_job(jid: int, p: Principal = Depends(require("workflows"))) -> dict:
    async with db.tx(system=True) as c:
        n = await c.execute("update jobs set status = 'queued', attempts = 0, run_at = now() where id = $1 and tenant_id = $2", jid, p.active)
    jobs._wake.set()
    return {"ok": n.endswith("1")}
