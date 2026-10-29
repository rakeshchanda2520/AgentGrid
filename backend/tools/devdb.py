"""Local Postgres 16 + pgvector without Docker: `uv run python -m tools.devdb [--hold]`.

Starts (or reuses) an embedded server in backend/.data/pg, creates a NON-superuser role `agentgrid`
(superusers bypass row-level security, so the app must never run as one), the `agentgrid` and
`agentgrid_test` databases with pgvector, and writes DATABASE_URL / TEST_DATABASE_URL plus fresh
secrets into backend/.env (secrets only if missing). `--hold` keeps the server process alive.
"""

import asyncio
import re
import secrets
import sys
import time
from pathlib import Path

import asyncpg
import pgserver
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".data" / "pg"
ENV = ROOT / ".env"


async def _prepare(admin_uri: str) -> dict[str, str]:
    base = admin_uri.rsplit("/", 1)[0]
    conn = await asyncpg.connect(admin_uri)
    if not await conn.fetchval("select 1 from pg_roles where rolname = 'agentgrid'"):
        await conn.execute("create role agentgrid login password 'agentgrid' nosuperuser nobypassrls")
    for name in ("agentgrid", "agentgrid_test"):
        if not await conn.fetchval("select 1 from pg_database where datname = $1", name):
            await conn.execute(f"create database {name} owner agentgrid")
        await conn.execute(f"alter database {name} owner to agentgrid")
    await conn.close()
    for name in ("agentgrid", "agentgrid_test"):
        conn = await asyncpg.connect(f"{base}/{name}")
        await conn.execute("create extension if not exists vector")
        await conn.close()
    host = base.split("@", 1)[1]
    return {
        "DATABASE_URL": f"postgresql://agentgrid:agentgrid@{host}/agentgrid",
        "TEST_DATABASE_URL": f"postgresql://agentgrid:agentgrid@{host}/agentgrid_test",
    }


def _write_env(values: dict[str, str]) -> None:
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    defaults = {"JWT_SECRET": secrets.token_urlsafe(48), "MASTER_KEY": Fernet.generate_key().decode()}
    for key, value in {**defaults, **values}.items():
        idx = next((i for i, line in enumerate(lines) if re.match(rf"{key}=", line)), None)
        if idx is None:
            lines.append(f"{key}={value}")
        elif key not in defaults:
            lines[idx] = f"{key}={value}"
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    DATA.mkdir(parents=True, exist_ok=True)
    srv = pgserver.get_server(str(DATA), cleanup_mode=None)
    urls = asyncio.run(_prepare(srv.get_uri()))
    _write_env(urls)
    print(urls["DATABASE_URL"], flush=True)
    while "--hold" in sys.argv:
        time.sleep(3600)
