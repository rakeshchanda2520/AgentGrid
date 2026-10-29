"""Channel adapters: normalize inbound payloads to one shape, send replies back.

WhatsApp: Meta Cloud API test number (no business verification needed).
Telegram: Bot API. Webhook when the API is public over HTTPS, long polling otherwise (local dev).
Web chat and the REST API channel live in api/public.py; they call conversations.inbound directly.
"""

import asyncio
import contextlib
import logging
from typing import Any
from uuid import UUID

import asyncpg
import httpx

from app import db, jobs
from app.config import settings
from app.conversations import inbound
from app.security import decrypt, encrypt, new_secret

log = logging.getLogger("agentgrid.channels")
TG = "https://api.telegram.org/bot{token}/{method}"


# ---------------------------------------------------------------- WhatsApp


def parse_whatsapp(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Meta webhook → [{phone_number_id, from, name, text, id}] (text messages and button replies only)."""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            v = change.get("value", {})
            names = {ct.get("wa_id"): ct.get("profile", {}).get("name") for ct in v.get("contacts", [])}
            for m in v.get("messages", []):
                text = (
                    (m.get("text") or {}).get("body")
                    or (m.get("button") or {}).get("text")
                    or ((m.get("interactive") or {}).get("button_reply") or {}).get("title")
                )
                if text:
                    out.append(
                        {
                            "phone_number_id": v.get("metadata", {}).get("phone_number_id"),
                            "from": m["from"],
                            "name": names.get(m["from"]),
                            "text": text,
                            "id": m["id"],
                        }
                    )
    return out


async def whatsapp_send(token: str, phone_number_id: str, to: str, text: str) -> None:
    url = f"https://graph.facebook.com/{settings().whatsapp_graph_version}/{phone_number_id}/messages"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            url, headers={"Authorization": f"Bearer {token}"}, json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:4096]}}
        )
        if r.status_code >= 400:
            raise RuntimeError(f"WhatsApp send failed {r.status_code}: {r.text[:300]}")


# ---------------------------------------------------------------- Telegram


async def telegram(token: str, method: str, **params: Any) -> Any:
    async with httpx.AsyncClient(timeout=40) as client:
        r = await client.post(TG.format(token=token, method=method), json=params)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {data.get('description')}")
        return data["result"]


def parse_telegram(update: dict[str, Any]) -> dict[str, Any] | None:
    m = update.get("message") or update.get("edited_message")
    if not m or not m.get("text"):
        return None
    sender = m.get("from", {})
    name = " ".join(x for x in (sender.get("first_name"), sender.get("last_name")) if x) or sender.get("username")
    text = m["text"]
    if text.startswith("/start"):
        text = "Hi"
    return {"chat_id": str(m["chat"]["id"]), "name": name, "text": text, "id": f"tg:{m['chat']['id']}:{m['message_id']}"}


def polling_enabled() -> bool:
    s = settings()
    return s.telegram_polling if s.telegram_polling is not None else not s.public_api_url.startswith("https://")


async def connect_telegram(c: asyncpg.Connection, tenant_id: UUID, agent_id: UUID, bot_token: str) -> dict[str, Any]:
    me = await telegram(bot_token, "getMe")
    secret = new_secret(n=24).replace("-", "a").replace("_", "b")
    conn = db.row(
        await c.fetchrow(
            """insert into channel_connections (tenant_id, agent_id, type, external_id, secrets_enc, webhook_secret, config)
           values ($1,$2,'telegram',$3,$4,$5,$6)
           on conflict (type, external_id) do update set agent_id = $2, secrets_enc = $4, webhook_secret = $5, config = $6, status = 'active'
           returning id, type, external_id, config, status""",
            tenant_id,
            agent_id,
            str(me["id"]),
            encrypt(tenant_id, {"bot_token": bot_token}),
            secret,
            {"username": me.get("username"), "name": me.get("first_name"), "offset": 0},
        )
    )
    if polling_enabled():
        await telegram(bot_token, "deleteWebhook")
        conn["mode"] = "polling (local development)"
    else:
        url = f"{settings().public_api_url}/webhooks/telegram/{conn['id']}"
        await telegram(bot_token, "setWebhook", url=url, secret_token=secret, allowed_updates=["message"])
        conn["mode"] = "webhook"
    conn["link"] = f"https://t.me/{me.get('username')}"
    return conn


async def handle_telegram_update(conn: dict[str, Any], update: dict[str, Any]) -> None:
    msg = parse_telegram(update)
    if msg:
        await inbound(
            conn["tenant_id"], conn["agent_id"], "telegram", msg["chat_id"], msg["text"], name=msg["name"], external_id=msg["id"], connection_id=conn["id"]
        )


async def telegram_poller() -> None:
    """ponytail: polls every Telegram bot every 2 s when there is no public HTTPS URL (local dev only)."""
    while True:
        try:
            async with db.tx(system=True) as c:
                conns = db.rows(await c.fetch("select * from channel_connections where type = 'telegram' and status = 'active'"))
            for conn in conns:
                token = decrypt(conn["tenant_id"], conn["secrets_enc"])["bot_token"]
                offset = (conn["config"] or {}).get("offset", 0)
                updates = await telegram(token, "getUpdates", offset=offset + 1, timeout=0, allowed_updates=["message"])
                for u in updates:
                    await handle_telegram_update(conn, u)
                    offset = max(offset, u["update_id"])
                if updates:
                    async with db.tx(system=True) as c:
                        await c.execute(
                            "update channel_connections set config = config || jsonb_build_object('offset', $2::int) where id = $1", conn["id"], offset
                        )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("telegram polling: %s", exc)
        await asyncio.sleep(2)


# ---------------------------------------------------------------- outbound job


@jobs.handler("channel.send")
async def send_job(payload: dict[str, Any], tenant_id: UUID | None) -> None:
    async with db.tx([tenant_id]) as c:
        row = await c.fetchrow(
            """select v.channel, k.channel_user_id, cc.external_id, cc.secrets_enc, cc.tenant_id
               from conversations v join contacts k on k.id = v.contact_id
               left join channel_connections cc on cc.id = v.connection_id where v.id = $1""",
            UUID(payload["conversation_id"]),
        )
    if not row or not row["secrets_enc"]:
        return
    secrets = decrypt(row["tenant_id"], row["secrets_enc"])
    if row["channel"] == "telegram":
        for i in range(0, len(payload["text"]), 4000):
            await telegram(secrets["bot_token"], "sendMessage", chat_id=row["channel_user_id"], text=payload["text"][i : i + 4000])
    elif row["channel"] == "whatsapp":
        await whatsapp_send(secrets["access_token"], row["external_id"], row["channel_user_id"], payload["text"])


async def start_background() -> list[asyncio.Task]:
    tasks = []
    if polling_enabled():
        tasks.append(asyncio.create_task(telegram_poller()))
    return tasks


async def stop(tasks: list[asyncio.Task]) -> None:
    for t in tasks:
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t
