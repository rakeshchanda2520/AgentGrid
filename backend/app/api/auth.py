from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app import db
from app.auth import Principal, audit, load_access, principal, role_on
from app.config import settings
from app.security import access_token, hash_password, new_secret, rate_limited, sha256, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class Login(BaseModel):
    email: str
    password: str


class Refresh(BaseModel):
    refresh_token: str


async def _issue(user_id) -> dict:
    token = new_secret("rt_")
    async with db.tx(system=True) as c:
        await c.execute(
            "insert into refresh_tokens (user_id, token_hash, expires_at) values ($1, $2, $3)",
            user_id,
            sha256(token),
            datetime.now(UTC) + timedelta(days=settings().refresh_token_days),
        )
    return {"access_token": access_token(user_id), "refresh_token": token, "expires_in": settings().access_token_minutes * 60}


@router.post("/login")
async def login(body: Login, request: Request) -> dict:
    ip = request.client.host if request.client else "?"
    if rate_limited(f"login:{ip}", 20) or rate_limited(f"login:{body.email.lower()}", 8):
        raise HTTPException(429, "Too many attempts. Wait a minute and try again.")
    async with db.tx(system=True) as c:
        user = await c.fetchrow("select id, password_hash, is_active from users where lower(email) = lower($1)", body.email.strip())
        ok = bool(user and user["is_active"] and verify_password(body.password, user["password_hash"]))
        await audit(c, None, user["id"] if user else None, "auth.login" if ok else "auth.login_failed", body.email.lower(), ip=ip)
    if not ok:
        raise HTTPException(401, "Wrong email or password")
    return await _issue(user["id"])


@router.post("/refresh")
async def refresh(body: Refresh) -> dict:
    async with db.tx(system=True) as c:
        uid = await c.fetchval(
            "update refresh_tokens set revoked_at = now() where token_hash = $1 and revoked_at is null and expires_at > now() returning user_id",
            sha256(body.refresh_token),
        )
    if not uid:
        raise HTTPException(401, "Session expired. Sign in again.")
    return await _issue(uid)


@router.post("/logout")
async def logout(body: Refresh) -> dict:
    async with db.tx(system=True) as c:
        await c.execute("update refresh_tokens set revoked_at = now() where token_hash = $1", sha256(body.refresh_token))
    return {"ok": True}


@router.get("/me")
async def me(p: Principal = Depends(principal)) -> dict:
    from app.api.public import brand_for

    _, tenants, roles = await load_access(p.id)
    async with db.tx(system=True) as c:  # resolved white-label (agency → client), even when the agency itself isn't visible
        brands = {t["id"]: await brand_for(c, t["id"]) for t in tenants}
    return {
        "user": {k: p.user[k] for k in ("id", "email", "name", "is_platform_admin")},
        "active_tenant": p.active,
        "role": p.role,
        "tenants": [t | {"role": role_on(p.user, roles, t), "brand": brands[t["id"]]} for t in tenants],
    }


class PasswordChange(BaseModel):
    current: str
    new: str


@router.post("/password")
async def change_password(body: PasswordChange, p: Principal = Depends(principal)) -> dict:
    if len(body.new) < 10:
        raise HTTPException(400, "Use at least 10 characters")
    async with db.tx(system=True) as c:
        h = await c.fetchval("select password_hash from users where id = $1", p.id)
        if not verify_password(body.current, h):
            raise HTTPException(400, "Current password is wrong")
        await c.execute("update users set password_hash = $2 where id = $1", p.id, hash_password(body.new))
        await audit(c, None, p.id, "auth.password_changed")
    return {"ok": True}
