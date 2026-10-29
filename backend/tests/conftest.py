"""Tests run against TEST_DATABASE_URL (a separate local DB from tools/devdb.py), wiped and re-seeded once per session.
The LLM is the offline demo model (no API key), so the suite needs no network."""

import os
import re
from pathlib import Path

import pytest

ENV = Path(__file__).resolve().parents[1] / ".env"
_env = dict(re.findall(r"^(\w+)=(.*)$", ENV.read_text(encoding="utf-8"), re.M)) if ENV.exists() else {}
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or _env.get("TEST_DATABASE_URL", "")
os.environ["LLM_API_KEY"] = ""
os.environ["SEED_ON_EMPTY"] = "false"
os.environ["TELEGRAM_POLLING"] = "false"
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import asyncpg  # noqa: E402
import httpx  # noqa: E402

from app import db, seed  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
async def database():
    assert os.environ["DATABASE_URL"], "set TEST_DATABASE_URL (run `uv run python -m tools.devdb`)"
    await db.migrate()
    conn = await asyncpg.connect(settings().database_url)
    await seed.wipe(conn)
    await conn.close()
    await seed.seed()
    yield
    await db.close()


@pytest.fixture(scope="session")
async def ids() -> dict:
    async with db.tx(system=True) as c:
        t = {r["slug"]: r["id"] for r in await c.fetch("select id, slug from tenants")}
        a = {r["public_key"]: r["id"] for r in await c.fetch("select id, public_key from agents")}
    return {"tenants": t, "agents": a}


@pytest.fixture(scope="session")
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def login(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    r = await client.post("/auth/login", json={"email": email, "password": settings().demo_password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
