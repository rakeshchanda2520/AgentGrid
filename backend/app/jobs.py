"""Durable background jobs on a Postgres table (the PoC's stand-in for Kafka; seam: `enqueue`).

Jobs are claimed with FOR UPDATE SKIP LOCKED, retried with exponential backoff, and parked as `dead`
after max_attempts (visible and retryable in the console). Jobs carrying a conversation_id run one at
a time per conversation so replies stay in order.
"""

import asyncio
import contextlib
import logging
import traceback
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from app import db
from app.config import settings

log = logging.getLogger("agentgrid.jobs")
Handler = Callable[[dict[str, Any], UUID | None], Awaitable[None]]
HANDLERS: dict[str, Handler] = {}
_wake = asyncio.Event()
_conv_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)  # ponytail: in-process; Kafka partitions in target


def handler(kind: str):
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return deco


async def enqueue(
    c: asyncpg.Connection,
    kind: str,
    payload: dict[str, Any],
    tenant_id: UUID | None = None,
    run_at: datetime | None = None,
    max_attempts: int = 3,
) -> int:
    job_id = await c.fetchval(
        "insert into jobs (tenant_id, kind, payload, run_at, max_attempts) values ($1, $2, $3, coalesce($4, now()), $5) returning id",
        tenant_id,
        kind,
        payload,
        run_at,
        max_attempts,
    )
    _wake.set()
    return job_id


async def _claim(limit: int) -> list[dict[str, Any]]:
    async with db.tx(system=True) as c:
        return db.rows(
            await c.fetch(
                """update jobs set status = 'running', locked_at = now(), attempts = attempts + 1
                   where id in (select id from jobs where status = 'queued' and run_at <= now()
                                order by run_at, id limit $1 for update skip locked)
                   returning id, tenant_id, kind, payload, attempts, max_attempts""",
                limit,
            )
        )


async def _finish(job: dict[str, Any], error: str | None) -> None:
    async with db.tx(system=True) as c:
        if error is None:
            await c.execute("update jobs set status = 'done', last_error = null where id = $1", job["id"])
        elif job["attempts"] >= job["max_attempts"]:
            await c.execute("update jobs set status = 'dead', last_error = $2 where id = $1", job["id"], error[-4000:])
        else:
            delay = 5 * 2 ** (job["attempts"] - 1)
            await c.execute(
                "update jobs set status = 'queued', last_error = $2, run_at = now() + make_interval(secs => $3) where id = $1",
                job["id"],
                error[-4000:],
                delay,
            )


async def run_one(job: dict[str, Any]) -> None:
    fn = HANDLERS.get(job["kind"])
    error = None
    try:
        if fn is None:
            raise RuntimeError(f"no handler for job kind {job['kind']}")
        conv = job["payload"].get("conversation_id")
        if conv:
            async with _conv_locks[conv]:
                await fn(job["payload"], job["tenant_id"])
        else:
            await fn(job["payload"], job["tenant_id"])
    except Exception:
        error = traceback.format_exc()
        log.warning("job %s (%s) failed: %s", job["id"], job["kind"], error.splitlines()[-1])
    await _finish(job, error)


async def recover_stuck() -> None:
    async with db.tx(system=True) as c:
        await c.execute("update jobs set status = 'queued' where status = 'running' and locked_at < now() - interval '5 minutes'")


async def run_forever() -> None:
    sem = asyncio.Semaphore(settings().job_concurrency)
    tasks: set[asyncio.Task] = set()
    last_recover = 0.0
    loop = asyncio.get_running_loop()
    while True:
        try:
            if loop.time() - last_recover > 60:
                await recover_stuck()
                last_recover = loop.time()
            free = settings().job_concurrency - len(tasks)
            batch = await _claim(free) if free > 0 else []
            for job in batch:
                await sem.acquire()
                t = asyncio.create_task(run_one(job))
                tasks.add(t)
                t.add_done_callback(lambda t: (tasks.discard(t), sem.release()))
            if not batch:
                _wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(_wake.wait(), timeout=1.0)
                await asyncio.sleep(0.05)  # ponytail: lets the enqueuing transaction commit before we claim
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("job runner loop error")
            await asyncio.sleep(2)


async def drain(max_rounds: int = 50) -> None:
    """Run every due job now (tests, seed, evals): no background loop needed."""
    for _ in range(max_rounds):
        batch = await _claim(50)
        if not batch:
            return
        for job in batch:
            await run_one(job)
