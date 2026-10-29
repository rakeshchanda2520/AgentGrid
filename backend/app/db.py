"""asyncpg pool + tenant-scoped transactions + a tiny SQL migration runner.

Every query runs inside `tx(...)`, which sets the RLS context for that transaction only:
  tx(tenant_ids)  → app.tenant_ids = the caller's allowed tenants (RLS filters everything else)
  tx(system=True) → app.system = 'on' for platform code paths (webhook routing, job claiming, seeding)
"""

import json
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg

from app.config import BACKEND_DIR, settings

_pool: asyncpg.Pool | None = None
MIGRATIONS = BACKEND_DIR / "migrations"


async def _init_conn(conn: asyncpg.Connection) -> None:
    for t in ("json", "jsonb"):
        await conn.set_type_codec(t, encoder=lambda v: json.dumps(v, default=str), decoder=json.loads, schema="pg_catalog")


async def connect() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings().database_url, min_size=1, max_size=10, init=_init_conn)
    return _pool


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def tx(tenant_ids: Iterable[UUID | str] | None = None, *, system: bool = False) -> AsyncIterator[asyncpg.Connection]:
    pool = await connect()
    async with pool.acquire() as conn, conn.transaction():
        if system:
            await conn.execute("select set_config('app.system', 'on', true)")
        else:
            ids = ",".join(str(t) for t in (tenant_ids or []))
            await conn.execute("select set_config('app.tenant_ids', $1, true)", ids)
        yield conn


def row(r: asyncpg.Record | None) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


def rows(rs: Iterable[asyncpg.Record]) -> list[dict[str, Any]]:
    return [dict(r) for r in rs]


def vec(values: Iterable[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in values) + "]"


async def migrate(url: str | None = None) -> list[str]:
    conn = await asyncpg.connect(url or settings().database_url)
    try:
        await conn.execute("create table if not exists schema_migrations (version text primary key, applied_at timestamptz default now())")
        done = {r["version"] for r in await conn.fetch("select version from schema_migrations")}
        applied = []
        for f in sorted(Path(MIGRATIONS).glob("*.sql")):
            if f.stem in done:
                continue
            async with conn.transaction():
                await conn.execute(f.read_text(encoding="utf-8"))
                await conn.execute("insert into schema_migrations (version) values ($1)", f.stem)
            applied.append(f.stem)
        return applied
    finally:
        await conn.close()


if __name__ == "__main__":
    import asyncio

    print("applied:", asyncio.run(migrate()) or "nothing new")
