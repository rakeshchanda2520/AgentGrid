from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app import analytics, db
from app.auth import Principal, require

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _scope(p: Principal) -> list[UUID]:
    """An agency workspace sees all its clients; a client workspace sees itself."""
    active = next(t for t in p.tenants if t["id"] == p.active)
    if active["kind"] == "agency":
        return [t["id"] for t in p.tenants if t["parent_id"] == p.active]
    if active["kind"] == "platform":
        return [t["id"] for t in p.tenants if t["kind"] == "client"]
    return [p.active]


@router.get("/overview")
async def overview(days: int = Query(30, ge=1, le=365), agent_id: UUID | None = None, p: Principal = Depends(require("analytics"))) -> dict:
    end = datetime.now(UTC) + timedelta(minutes=1)
    async with p.tx() as c:
        return await analytics.overview(c, _scope(p), end - timedelta(days=days), end, agent_id)


@router.get("/agency")
async def agency(days: int = Query(30, ge=1, le=365), p: Principal = Depends(require("analytics"))) -> list[dict]:
    end = datetime.now(UTC) + timedelta(minutes=1)
    async with p.tx() as c:
        return await analytics.agency_rollup(c, _scope(p), end - timedelta(days=days), end)


@router.get("/live")
async def live(p: Principal = Depends(require("analytics"))) -> dict:
    async with p.tx() as c:
        return db.row(
            await c.fetchrow(
                """select count(*) filter (where state = 'PENDING_HUMAN') as waiting_for_human,
                      count(*) filter (where state = 'HUMAN_ACTIVE') as with_human,
                      count(*) filter (where state = 'BOT_ACTIVE' and last_message_at > now() - interval '15 minutes') as active_with_ai
               from conversations where tenant_id = any($1) and channel <> 'playground'""",
                _scope(p),
            )
        )
