"""AI model providers, agents, knowledge, catalog, channel connections and the playground."""

from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app import channels, conversations, db, jobs, rag, templates
from app.agent.graph import mermaid
from app.api.admin import create_agent
from app.auth import Principal, audit, require
from app.config import settings
from app.llm import BASE_URLS, ModelSpec, chat_model, platform_spec
from app.security import decrypt, encrypt, new_secret

router = APIRouter(tags=["agents"])
PROVIDER_KINDS = ["openrouter", "openai", "anthropic", "qwen", "ollama", "openai_compat"]


async def _agent(c, p: Principal, aid: UUID) -> dict[str, Any]:
    a = db.row(await c.fetchrow("select * from agents where id = $1 and tenant_id = $2", aid, p.active))
    if not a:
        raise HTTPException(404, "Agent not found")
    return a


@router.get("/templates")
async def list_templates() -> list[dict]:
    return templates.summary()


# ---------------------------------------------------------------- model providers


class Provider(BaseModel):
    name: str
    kind: str = Field(pattern="^(openrouter|openai|anthropic|qwen|ollama|openai_compat)$")
    base_url: str | None = None
    api_key: str | None = None
    default_model: str
    cheap_model: str | None = None


def _public_provider(p: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in p.items() if k != "api_key_enc"}
    return out | {"has_key": bool(p.get("api_key_enc"))}


async def _test(spec: ModelSpec) -> dict[str, Any]:
    if spec.offline:
        return {"ok": False, "error": "No API key set"}
    try:
        from langchain_core.tools import tool

        @tool
        def ping(word: str) -> str:
            """Echo a word back. Call this with word='ok'."""
            return word

        resp = await chat_model(spec, max_tokens=60).bind_tools([ping]).ainvoke([HumanMessage("Call the ping tool with word 'ok'.")])
        return {"ok": True, "tool_calling": bool(resp.tool_calls), "model": spec.model}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


@router.get("/llm-providers")
async def list_providers(p: Principal = Depends(require("models"))) -> dict:
    async with p.tx() as c:
        rows = db.rows(await c.fetch("select * from llm_providers where tenant_id = $1 order by created_at", p.active))
    plat = platform_spec()
    return {
        "providers": [_public_provider(r) for r in rows],
        "kinds": PROVIDER_KINDS,
        "base_urls": BASE_URLS,
        "platform_default": {"kind": plat.kind, "model": plat.model, "offline": plat.offline, "cheap_model": platform_spec(True).model},
    }


@router.post("/llm-providers")
async def create_provider(body: Provider, p: Principal = Depends(require("models"))) -> dict:
    async with p.tx() as c:
        row = db.row(
            await c.fetchrow(
                """insert into llm_providers (tenant_id, name, kind, base_url, api_key_enc, default_model, cheap_model)
               values ($1,$2,$3,$4,$5,$6,$7) returning *""",
                p.active,
                body.name,
                body.kind,
                body.base_url,
                encrypt(p.active, body.api_key) if body.api_key else None,
                body.default_model,
                body.cheap_model,
            )
        )
        await audit(c, p.active, p.id, "llm_provider.created", body.name, {"kind": body.kind, "model": body.default_model})
    return _public_provider(row)


@router.patch("/llm-providers/{pid}")
async def update_provider(pid: UUID, body: Provider, p: Principal = Depends(require("models"))) -> dict:
    async with p.tx() as c:
        row = db.row(
            await c.fetchrow(
                """update llm_providers set name = $3, kind = $4, base_url = $5, default_model = $6, cheap_model = $7,
               api_key_enc = coalesce($8, api_key_enc) where id = $1 and tenant_id = $2 returning *""",
                pid,
                p.active,
                body.name,
                body.kind,
                body.base_url,
                body.default_model,
                body.cheap_model,
                encrypt(p.active, body.api_key) if body.api_key else None,
            )
        )
        if not row:
            raise HTTPException(404)
        await audit(c, p.active, p.id, "llm_provider.updated", body.name)
    return _public_provider(row)


@router.delete("/llm-providers/{pid}")
async def delete_provider(pid: UUID, p: Principal = Depends(require("models"))) -> dict:
    async with p.tx() as c:
        await c.execute("delete from llm_providers where id = $1 and tenant_id = $2", pid, p.active)
        await audit(c, p.active, p.id, "llm_provider.deleted", str(pid))
    return {"ok": True}


@router.post("/llm-providers/{pid}/test")
async def test_provider(pid: UUID, p: Principal = Depends(require("models"))) -> dict:
    async with p.tx() as c:
        r = await c.fetchrow("select * from llm_providers where id = $1 and tenant_id = $2", pid, p.active)
    if not r:
        raise HTTPException(404)
    return await _test(
        ModelSpec(kind=r["kind"], model=r["default_model"], api_key=decrypt(r["tenant_id"], r["api_key_enc"]) or "", base_url=r["base_url"] or "")
    )


@router.post("/llm-providers/test-platform")
async def test_platform(p: Principal = Depends(require("models"))) -> dict:
    return await _test(platform_spec())


@router.get("/llm-providers/{pid}/models")
async def provider_models(pid: UUID, p: Principal = Depends(require("models"))) -> list[str]:
    async with p.tx() as c:
        r = await c.fetchrow("select * from llm_providers where id = $1 and tenant_id = $2", pid, p.active)
    if not r or r["kind"] == "anthropic":
        return []
    base = r["base_url"] or BASE_URLS.get(r["kind"]) or "https://api.openai.com/v1"
    key = decrypt(r["tenant_id"], r["api_key_enc"]) or ""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{base.rstrip('/')}/models", headers={"Authorization": f"Bearer {key}"} if key else {})
            return sorted(m["id"] for m in resp.json().get("data", []))[:500]
    except Exception:
        return []


# ---------------------------------------------------------------- agents


class NewAgent(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    template_key: str
    persona: str | None = None


class AgentUpdate(BaseModel):
    name: str | None = None
    persona: str | None = None
    status: str | None = Field(None, pattern="^(active|paused)$")
    provider_id: UUID | None = None
    model: str | None = None
    cheap_model: str | None = None
    fallback_provider_id: UUID | None = None
    fallback_model: str | None = None
    config: dict[str, Any] | None = None
    clear_provider: bool = False


@router.get("/agents")
async def list_agents(p: Principal = Depends(require("analytics"))) -> list[dict]:
    async with p.tx() as c:
        return db.rows(
            await c.fetch(
                """select a.id, a.name, a.template_key, a.public_key, a.status, a.model, a.provider_id, a.created_at,
                      (select count(*) from conversations v where v.agent_id = a.id) as conversations,
                      (select count(*) from knowledge_sources k where k.agent_id = a.id) as sources,
                      (select coalesce(array_agg(type), '{}') from channel_connections cc where cc.agent_id = a.id) as channels
               from agents a where a.tenant_id = $1 order by a.created_at""",
                p.active,
            )
        )


@router.post("/agents")
async def new_agent(body: NewAgent, p: Principal = Depends(require("agents"))) -> dict:
    if body.template_key not in templates.all_templates():
        raise HTTPException(400, "Unknown template")
    async with p.tx() as c:
        agent = await create_agent(c, p.active, body.name, body.template_key, body.persona)
        await audit(c, p.active, p.id, "agent.created", body.name, {"template": body.template_key})
    return agent


@router.get("/agents/graph")
async def agent_graph() -> dict:
    return {"mermaid": mermaid()}


@router.get("/agents/{aid}")
async def get_agent(aid: UUID, p: Principal = Depends(require("analytics"))) -> dict:
    async with p.tx() as c:
        a = await _agent(c, p, aid)
        chans = db.rows(
            await c.fetch("select id, type, external_id, config, status, created_at, webhook_secret from channel_connections where agent_id = $1", aid)
        )
    for ch in chans:
        secret = ch.pop("webhook_secret")
        if ch["type"] == "whatsapp":  # Meta's verify token: needed again when re-pasting the webhook config (Telegram's secret is never shown)
            ch["webhook_url"] = f"{settings().public_api_url}/webhooks/whatsapp/{ch['id']}"
            ch["verify_token"] = secret if p.can("agents") else None
    return a | {"channels": chans, "widget_script": f'<script src="{settings().public_api_url}/widget.js" data-agent="{a["public_key"]}" async></script>'}


@router.patch("/agents/{aid}")
async def update_agent(aid: UUID, body: AgentUpdate, p: Principal = Depends(require("agents"))) -> dict:
    async with p.tx() as c:
        a = await _agent(c, p, aid)
        data = body.model_dump(exclude_unset=True, exclude={"clear_provider"})
        if body.clear_provider:
            data |= {"provider_id": None, "model": None, "cheap_model": None}
        if "config" in data:
            data["config"] = a["config"] | data["config"]
        for pid in (data.get("provider_id"), data.get("fallback_provider_id")):
            if pid and not await c.fetchval("select 1 from llm_providers where id = $1 and tenant_id = $2", pid, p.active):
                raise HTTPException(400, "Provider not found in this workspace")
        if data:
            sets = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(data))
            a = db.row(await c.fetchrow(f"update agents set {sets} where id = $1 returning *", aid, *data.values()))
        await audit(c, p.active, p.id, "agent.updated", a["name"], {"fields": list(data)})
    return a


@router.delete("/agents/{aid}")
async def delete_agent(aid: UUID, p: Principal = Depends(require("agents"))) -> dict:
    async with p.tx() as c:
        a = await _agent(c, p, aid)
        await c.execute("delete from agents where id = $1", aid)
        await audit(c, p.active, p.id, "agent.deleted", a["name"])
    return {"ok": True}


# ---------------------------------------------------------------- knowledge


@router.get("/agents/{aid}/knowledge")
async def list_knowledge(aid: UUID, p: Principal = Depends(require("analytics"))) -> list[dict]:
    async with p.tx() as c:
        await _agent(c, p, aid)
        return db.rows(
            await c.fetch(
                "select id, type, title, uri, status, error, chunk_count, created_at from knowledge_sources where agent_id = $1 order by created_at desc", aid
            )
        )


async def _add_source(p: Principal, aid: UUID, type_: str, title: str, uri: str | None, text: str | None) -> dict:
    async with p.tx() as c:
        await _agent(c, p, aid)
        src = db.row(
            await c.fetchrow(
                "insert into knowledge_sources (tenant_id, agent_id, type, title, uri, raw_text) values ($1,$2,$3,$4,$5,$6) returning id, type, title, status",
                p.active,
                aid,
                type_,
                title,
                uri,
                text,
            )
        )
        await jobs.enqueue(c, "kb.ingest", {"source_id": str(src["id"])}, p.active)
        await audit(c, p.active, p.id, "knowledge.added", title, {"type": type_})
    return src


@router.post("/agents/{aid}/knowledge/file")
async def upload_file(aid: UUID, file: UploadFile = File(...), title: str | None = Form(None), p: Principal = Depends(require("agents"))) -> dict:
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "File too large (15 MB max)")
    name = file.filename or "document.txt"
    if not name.lower().endswith((".pdf", ".docx", ".txt", ".md", ".csv", ".html", ".htm", ".json")):
        raise HTTPException(400, "Supported: PDF, DOCX, TXT, MD, CSV, HTML")
    try:
        text = rag.extract_text(name, data)
    except Exception as exc:
        raise HTTPException(400, f"Could not read the file: {exc}") from exc
    if not text.strip():
        raise HTTPException(400, "No text found in the file (scanned PDFs need OCR, which is on the roadmap)")
    return await _add_source(p, aid, "file", title or name, name, text)


class TextSource(BaseModel):
    title: str
    text: str = Field(min_length=10, max_length=200_000)


@router.post("/agents/{aid}/knowledge/text")
async def add_text(aid: UUID, body: TextSource, p: Principal = Depends(require("agents"))) -> dict:
    return await _add_source(p, aid, "faq", body.title, None, body.text)


class UrlSource(BaseModel):
    url: str


@router.post("/agents/{aid}/knowledge/url")
async def add_url(aid: UUID, body: UrlSource, p: Principal = Depends(require("agents"))) -> dict:
    return await _add_source(p, aid, "url", body.url, body.url, None)


@router.delete("/knowledge/{sid}")
async def delete_source(sid: UUID, p: Principal = Depends(require("agents"))) -> dict:
    async with p.tx() as c:
        await c.execute("delete from knowledge_sources where id = $1 and tenant_id = $2", sid, p.active)
        await audit(c, p.active, p.id, "knowledge.deleted", str(sid))
    return {"ok": True}


@router.post("/knowledge/{sid}/reindex")
async def reindex(sid: UUID, p: Principal = Depends(require("agents"))) -> dict:
    async with p.tx() as c:
        await c.execute("update knowledge_sources set status = 'queued' where id = $1 and tenant_id = $2", sid, p.active)
        await jobs.enqueue(c, "kb.ingest", {"source_id": str(sid)}, p.active)
    return {"ok": True}


class SearchQuery(BaseModel):
    query: str


@router.post("/agents/{aid}/knowledge/search")
async def test_search(aid: UUID, body: SearchQuery, p: Principal = Depends(require("analytics"))) -> dict:
    async with p.tx() as c:
        await _agent(c, p, aid)
    hits, confident = await rag.search(p.active, aid, body.query)
    return {
        "confident": confident,
        "results": [
            {"title": h["title"], "page": h["page"], "content": h["content"].split("\n", 1)[-1], "similarity": h["sim"], "text_rank": h["rank"]} for h in hits
        ],
    }


# ---------------------------------------------------------------- catalog


class Item(BaseModel):
    name: str
    description: str = ""
    price: float | None = None
    attributes: dict[str, Any] = {}


@router.get("/agents/{aid}/catalog")
async def list_catalog(aid: UUID, p: Principal = Depends(require("analytics"))) -> list[dict]:
    async with p.tx() as c:
        await _agent(c, p, aid)
        return db.rows(await c.fetch("select * from catalog_items where agent_id = $1 order by price nulls last", aid))


@router.post("/agents/{aid}/catalog")
async def add_item(aid: UUID, body: Item, p: Principal = Depends(require("agents"))) -> dict:
    async with p.tx() as c:
        await _agent(c, p, aid)
        return db.row(
            await c.fetchrow(
                "insert into catalog_items (tenant_id, agent_id, name, description, price, attributes) values ($1,$2,$3,$4,$5,$6) returning *",
                p.active,
                aid,
                body.name,
                body.description,
                body.price,
                body.attributes,
            )
        )


@router.delete("/catalog/{iid}")
async def delete_item(iid: UUID, p: Principal = Depends(require("agents"))) -> dict:
    async with p.tx() as c:
        await c.execute("delete from catalog_items where id = $1 and tenant_id = $2", iid, p.active)
    return {"ok": True}


# ---------------------------------------------------------------- channels


class TelegramConnect(BaseModel):
    bot_token: str = Field(min_length=20)


class WhatsAppConnect(BaseModel):
    phone_number_id: str
    access_token: str
    app_secret: str
    verify_token: str | None = None


@router.post("/agents/{aid}/channels/telegram")
async def connect_telegram(aid: UUID, body: TelegramConnect, p: Principal = Depends(require("agents"))) -> dict:
    async with p.tx() as c:
        await _agent(c, p, aid)
        try:
            conn = await channels.connect_telegram(c, p.active, aid, body.bot_token.strip())
        except Exception as exc:
            raise HTTPException(400, f"Telegram rejected the token: {exc}") from exc
        await audit(c, p.active, p.id, "channel.connected", "telegram", {"bot": conn["config"].get("username")})
    return conn


@router.post("/agents/{aid}/channels/whatsapp")
async def connect_whatsapp(aid: UUID, body: WhatsAppConnect, p: Principal = Depends(require("agents"))) -> dict:
    verify = body.verify_token or new_secret(n=12)
    async with p.tx() as c:
        await _agent(c, p, aid)
        conn = db.row(
            await c.fetchrow(
                """insert into channel_connections (tenant_id, agent_id, type, external_id, secrets_enc, webhook_secret, config)
               values ($1,$2,'whatsapp',$3,$4,$5,'{}')
               on conflict (type, external_id) do update set agent_id = $2, secrets_enc = $4, webhook_secret = $5, status = 'active'
               returning id, type, external_id, status""",
                p.active,
                aid,
                body.phone_number_id.strip(),
                encrypt(p.active, {"access_token": body.access_token.strip(), "app_secret": body.app_secret.strip()}),
                verify,
            )
        )
        await audit(c, p.active, p.id, "channel.connected", "whatsapp", {"phone_number_id": body.phone_number_id})
    return conn | {
        "webhook_url": f"{settings().public_api_url}/webhooks/whatsapp/{conn['id']}",
        "verify_token": verify,
        "next_step": "In Meta for Developers → WhatsApp → Configuration, paste this Callback URL and Verify token, then subscribe to 'messages'.",
    }


@router.delete("/channels/{cid}")
async def disconnect(cid: UUID, p: Principal = Depends(require("agents"))) -> dict:
    async with p.tx() as c:
        row = await c.fetchrow("select type, secrets_enc from channel_connections where id = $1 and tenant_id = $2", cid, p.active)
        if row and row["type"] == "telegram":
            try:
                await channels.telegram(decrypt(p.active, row["secrets_enc"])["bot_token"], "deleteWebhook")
            except Exception:  # noqa: S110 - best effort, the connection is removed either way
                pass
        await c.execute("delete from channel_connections where id = $1 and tenant_id = $2", cid, p.active)
        await audit(c, p.active, p.id, "channel.disconnected", str(cid))
    return {"ok": True}


# ---------------------------------------------------------------- playground


class PlaygroundMsg(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    session: str = "default"


@router.post("/agents/{aid}/playground")
async def playground(aid: UUID, body: PlaygroundMsg, p: Principal = Depends(require("agents"))) -> dict:
    async with p.tx() as c:
        await _agent(c, p, aid)
    user_ref = f"pg:{p.id}:{body.session}"
    res = await conversations.inbound(p.active, aid, "playground", user_ref, body.text, name=p.user["name"], simulated=True, auto_reply=False)
    if res.get("state") != "BOT_ACTIVE":
        return res | {"reply": None, "note": "Conversation is with a human agent. Reset the session or return it to the bot."}
    turn = await conversations.reply_now(p.active, res["conversation_id"])
    return res | (turn or {})


@router.post("/agents/{aid}/playground/reset")
async def playground_reset(aid: UUID, body: PlaygroundMsg, p: Principal = Depends(require("agents"))) -> dict:
    async with p.tx() as c:
        await c.execute(
            """update conversations set state = 'RESOLVED', resolved_at = now(), last_message_at = now() - interval '1 day'
               where agent_id = $1 and tenant_id = $2 and contact_id in
                 (select id from contacts where channel = 'playground' and channel_user_id = $3)""",
            aid,
            p.active,
            f"pg:{p.id}:{body.session}",
        )
    return {"ok": True}
