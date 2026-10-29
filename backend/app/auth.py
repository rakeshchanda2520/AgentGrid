"""Who is calling, which tenants they may touch, and what they may do there (RBAC)."""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import Depends, Header, HTTPException, Request

from app import db
from app.security import decode_access, sha256

PERMS: dict[str, set[str]] = {
    "platform_admin": {"*"},
    "agency_admin": {"clients", "branding", "models", "agents", "inbox", "leads", "workflows", "analytics", "users", "audit"},
    "client_admin": {"models", "agents", "inbox", "leads", "workflows", "analytics", "users", "audit"},
    "human_agent": {"inbox", "leads", "analytics"},
    "viewer": {"analytics"},
}


@dataclass
class Principal:
    user: dict[str, Any]
    allowed: set[UUID]  # every tenant this user may see (agency → its clients); RLS context
    active: UUID  # tenant selected via X-Tenant-Id
    role: str  # role on the active tenant
    tenants: list[dict[str, Any]] = field(default_factory=list)

    @property
    def id(self) -> UUID:
        return self.user["id"]

    def can(self, perm: str) -> bool:
        perms = PERMS.get(self.role, set())
        return "*" in perms or perm in perms

    def tx(self):
        return db.tx(self.allowed)


async def load_access(user_id: UUID) -> tuple[dict[str, Any], list[dict[str, Any]], dict[UUID, str]] | None:
    """User row, visible tenants and direct roles. Users/tenants/memberships are platform tables (no RLS)."""
    async with db.tx(system=True) as c:
        user = db.row(await c.fetchrow("select id, email, name, is_platform_admin, is_active from users where id = $1", user_id))
        if not user or not user["is_active"]:
            return None
        if user["is_platform_admin"]:
            tenants = db.rows(await c.fetch("select id, parent_id, kind, name, slug, branding from tenants order by kind, name"))
            return user, tenants, {}
        roles = {r["tenant_id"]: r["role"] for r in await c.fetch("select tenant_id, role from memberships where user_id = $1", user_id)}
        tenants = db.rows(
            await c.fetch(
                """select id, parent_id, kind, name, slug, branding from tenants
                   where id = any($1::uuid[]) or parent_id = any($2::uuid[]) order by kind, name""",
                list(roles),
                [t for t, r in roles.items() if r == "agency_admin"],
            )
        )
        return user, tenants, roles


def role_on(user: dict[str, Any], roles: dict[UUID, str], tenant: dict[str, Any]) -> str | None:
    if user["is_platform_admin"]:
        return "platform_admin"
    return roles.get(tenant["id"]) or (roles.get(tenant["parent_id"]) if tenant["parent_id"] else None)


async def principal(request: Request, x_tenant_id: str | None = Header(default=None)) -> Principal:
    auth = request.headers.get("authorization", "")
    user_id = decode_access(auth.removeprefix("Bearer ").strip()) if auth.startswith("Bearer ") else None
    access = await load_access(user_id) if user_id else None
    if not access:
        raise HTTPException(401, "Not signed in")
    user, tenants, roles = access
    by_id = {t["id"]: t for t in tenants}
    if x_tenant_id:
        try:
            active = UUID(x_tenant_id)
        except ValueError:
            raise HTTPException(400, "Bad X-Tenant-Id") from None
        if active not in by_id:
            raise HTTPException(403, "No access to this workspace")
    else:
        preferred = [t for t in tenants if t["kind"] == "client"] or tenants
        if not preferred:
            raise HTTPException(403, "No workspace assigned")
        active = preferred[0]["id"]
    role = role_on(user, roles, by_id[active])
    if not role:
        raise HTTPException(403, "No role in this workspace")
    return Principal(user=user, allowed=set(by_id), active=active, role=role, tenants=tenants)


def require(perm: str):
    async def dep(p: Principal = Depends(principal)) -> Principal:
        if not p.can(perm):
            raise HTTPException(403, f"Your role ({p.role}) cannot do this")
        return p

    return dep


async def api_key_tenant(request: Request) -> UUID:
    key = request.headers.get("x-api-key") or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not key.startswith("ag_"):
        raise HTTPException(401, "API key required (X-API-Key: ag_...)")
    async with db.tx(system=True) as c:
        tid = await c.fetchval("update api_keys set last_used_at = now() where key_hash = $1 and revoked_at is null returning tenant_id", sha256(key))
    if not tid:
        raise HTTPException(401, "Invalid API key")
    return tid


async def audit(
    c: asyncpg.Connection,
    tenant_id: UUID | None,
    user_id: UUID | None,
    action: str,
    target: str = "",
    meta: dict | None = None,
    ip: str | None = None,
) -> None:
    await c.execute(
        "insert into audit_logs (tenant_id, user_id, action, target, meta, ip) values ($1, $2, $3, $4, $5, $6)",
        tenant_id,
        user_id,
        action,
        target,
        meta or {},
        ip,
    )
