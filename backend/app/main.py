import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from app import channels, conversations, db, jobs, rag, workflows  # noqa: F401  (rag/workflows register job handlers)
from app.api import admin, agents, analytics, auth, inbox, public
from app.api import workflows as workflows_api
from app.config import settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": self.formatTime(record), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)[-2000:]
        return json.dumps(out)


_h = logging.StreamHandler()
_h.setFormatter(JsonFormatter())
logging.basicConfig(level=settings().log_level, handlers=[_h], force=True)
log = logging.getLogger("agentgrid")

HTTP_LATENCY = Histogram("agentgrid_http_seconds", "HTTP latency", ["route", "method", "status"])
JOBS = Gauge("agentgrid_jobs", "Jobs by status", ["status"])
ERRORS = Counter("agentgrid_unhandled_errors_total", "Unhandled API errors")


async def _maintenance_loop() -> None:
    while True:
        try:
            await conversations.maintenance()
        except Exception:
            log.exception("maintenance failed")
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    applied = await db.migrate()
    if applied:
        log.info("migrations applied: %s", applied)
    await db.connect()
    if settings().seed_on_empty:
        from app import seed

        await seed.seed_if_empty()
    tasks = [asyncio.create_task(jobs.run_forever()), asyncio.create_task(_maintenance_loop())]
    tasks += await channels.start_background()
    log.info("AgentGrid API ready (llm=%s, embeddings=%s)", settings().llm_provider if settings().llm_api_key else "offline-demo", settings().embeddings)
    yield
    for t in tasks:
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t
    await db.close()


app = FastAPI(
    title="AgentGrid API",
    version="0.1.0",
    lifespan=lifespan,
    description="Multi-tenant AI agents for customer engagement and business automation. Console: see README.",
)
# Bearer tokens in headers (no cookies), so a wildcard origin carries no CSRF risk and lets any customer site embed the widget.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=False)


@app.middleware("http")
async def metrics_mw(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        ERRORS.inc()
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        response = JSONResponse({"detail": "Internal error"}, status_code=500)
    route = request.scope.get("route")
    HTTP_LATENCY.labels(getattr(route, "path", "unmatched"), request.method, response.status_code).observe(time.perf_counter() - start)
    return response


for r in (auth.router, admin.router, agents.router, inbox.router, workflows_api.router, analytics.router, public.router):
    app.include_router(r)


@app.get("/healthz", tags=["ops"])
async def healthz() -> dict:
    async with db.tx(system=True) as c:
        await c.fetchval("select 1")
    return {"ok": True}


@app.get("/metrics", tags=["ops"])
async def metrics() -> Response:
    async with db.tx(system=True) as c:
        for r in await c.fetch("select status, count(*) as n from jobs group by status"):
            JOBS.labels(r["status"]).set(r["n"])
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"name": "AgentGrid API", "docs": "/docs", "health": "/healthz"}
