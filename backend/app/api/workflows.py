from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import db, jobs, workflows
from app.auth import Principal, audit, require

router = APIRouter(tags=["workflows"])


class Workflow(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    trigger: dict[str, Any]
    steps: list[dict[str, Any]]
    enabled: bool = True


def _validate(body: Workflow) -> None:
    if body.trigger.get("event") not in workflows.EVENTS:
        raise HTTPException(400, f"Trigger event must be one of {workflows.EVENTS}")
    ids = set()
    for s in body.steps:
        if s.get("action") not in workflows.ACTIONS:
            raise HTTPException(400, f"Unknown action {s.get('action')}")
        if not s.get("id") or s["id"] in ids:
            raise HTTPException(400, "Every step needs a unique id")
        ids.add(s["id"])


@router.get("/workflows/meta")
async def meta() -> dict:
    return {"events": workflows.EVENTS, "actions": workflows.ACTIONS, "ops": ["==", "!=", ">", ">=", "<", "<=", "in", "contains", "exists"]}


@router.get("/workflows")
async def list_workflows(p: Principal = Depends(require("workflows"))) -> list[dict]:
    async with p.tx() as c:
        return db.rows(
            await c.fetch(
                """select w.*, (select count(*) from workflow_runs r where r.workflow_id = w.id) as runs,
                      (select count(*) from workflow_runs r where r.workflow_id = w.id and r.status = 'failed') as failed
               from workflows w where w.tenant_id = $1 order by w.created_at""",
                p.active,
            )
        )


@router.post("/workflows")
async def create(body: Workflow, p: Principal = Depends(require("workflows"))) -> dict:
    _validate(body)
    async with p.tx() as c:
        row = db.row(
            await c.fetchrow(
                "insert into workflows (tenant_id, name, trigger, steps, enabled) values ($1,$2,$3,$4,$5) returning *",
                p.active,
                body.name,
                body.trigger,
                body.steps,
                body.enabled,
            )
        )
        await audit(c, p.active, p.id, "workflow.created", body.name)
    return row


@router.patch("/workflows/{wid}")
async def update(wid: UUID, body: Workflow, p: Principal = Depends(require("workflows"))) -> dict:
    _validate(body)
    async with p.tx() as c:
        row = db.row(
            await c.fetchrow(
                "update workflows set name = $3, trigger = $4, steps = $5, enabled = $6 where id = $1 and tenant_id = $2 returning *",
                wid,
                p.active,
                body.name,
                body.trigger,
                body.steps,
                body.enabled,
            )
        )
        if not row:
            raise HTTPException(404)
        await audit(c, p.active, p.id, "workflow.updated", body.name)
    return row


@router.delete("/workflows/{wid}")
async def delete(wid: UUID, p: Principal = Depends(require("workflows"))) -> dict:
    async with p.tx() as c:
        await c.execute("delete from workflows where id = $1 and tenant_id = $2", wid, p.active)
        await audit(c, p.active, p.id, "workflow.deleted", str(wid))
    return {"ok": True}


@router.get("/workflow-runs")
async def runs(workflow_id: UUID | None = None, p: Principal = Depends(require("workflows"))) -> list[dict]:
    async with p.tx() as c:
        rs = db.rows(
            await c.fetch(
                """select r.id, r.workflow_id, w.name as workflow_name, r.status, r.error, r.event, r.outputs, r.created_at, r.finished_at
               from workflow_runs r join workflows w on w.id = r.workflow_id
               where r.tenant_id = $1 and ($2::uuid is null or r.workflow_id = $2) order by r.created_at desc limit 100""",
                p.active,
                workflow_id,
            )
        )
        steps = db.rows(
            await c.fetch(
                "select run_id, step_id, action, status, attempts, output, error, created_at from workflow_step_runs where run_id = any($1::uuid[]) order by created_at",
                [r["id"] for r in rs],
            )
        )
    by_run: dict[Any, list] = {}
    for s in steps:
        by_run.setdefault(s["run_id"], []).append(s)
    return [r | {"steps": by_run.get(r["id"], [])} for r in rs]


@router.post("/workflow-runs/{rid}/retry")
async def retry(rid: UUID, p: Principal = Depends(require("workflows"))) -> dict:
    async with p.tx() as c:
        run = await c.fetchrow(
            "select r.id, w.steps from workflow_runs r join workflows w on w.id = r.workflow_id where r.id = $1 and r.tenant_id = $2", rid, p.active
        )
        if not run:
            raise HTTPException(404)
        done = {s["step_id"] for s in await c.fetch("select step_id from workflow_step_runs where run_id = $1 and status = 'succeeded'", rid)}
        index = next((i for i, s in enumerate(run["steps"]) if s["id"] not in done), len(run["steps"]))
        await c.execute("update workflow_runs set status = 'running', error = null where id = $1", rid)
        await jobs.enqueue(c, "workflow.step", {"run_id": str(rid), "index": index}, p.active)
        await audit(c, p.active, p.id, "workflow_run.retried", str(rid))
    return {"ok": True, "from_step": index}
