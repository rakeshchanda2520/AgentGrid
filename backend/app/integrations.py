"""Outbound integrations. Every one is optional except the built-in email Outbox."""

import asyncio
import json
import logging
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from app.config import settings
from app.security import decrypt, sign_payload

log = logging.getLogger("agentgrid.integrations")


async def tenant_secrets(c: asyncpg.Connection, tenant_id: UUID) -> dict[str, Any]:
    return decrypt(tenant_id, await c.fetchval("select secrets_enc from tenants where id = $1", tenant_id)) or {}


def make_ics(summary: str, start: datetime, end: datetime, organizer: str, description: str = "") -> str:
    fmt = "%Y%m%dT%H%M%SZ"
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//AgentGrid//EN",
            "METHOD:REQUEST",
            "BEGIN:VEVENT",
            f"UID:{uuid4()}@agentgrid",
            f"DTSTAMP:{datetime.now(UTC).strftime(fmt)}",
            f"DTSTART:{start.astimezone(UTC).strftime(fmt)}",
            f"DTEND:{end.astimezone(UTC).strftime(fmt)}",
            f"SUMMARY:{summary}",
            f"ORGANIZER;CN={organizer}:mailto:no-reply@agentgrid.local",
            f"DESCRIPTION:{description.replace(chr(10), ' ')}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


def _smtp_send(to: str, subject: str, body: str, ics: str | None) -> None:
    s = settings()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(body)
    if ics:
        msg.add_attachment(ics.encode(), maintype="text", subtype="calendar", filename="invite.ics")
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
        smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


async def send_email(c: asyncpg.Connection, tenant_id: UUID, to: str, subject: str, body: str, ics: str | None = None) -> dict:
    """Always stored in the Outbox (visible in the console); also sent over SMTP when configured."""
    status, error = "stored", None
    if settings().smtp_host:
        try:
            await asyncio.to_thread(_smtp_send, to, subject, body, ics)
            status = "sent"
        except Exception as exc:
            status, error = "failed", str(exc)[:300]
    eid = await c.fetchval(
        "insert into outbox_emails (tenant_id, to_addr, subject, body, ics, status, error) values ($1,$2,$3,$4,$5,$6,$7) returning id",
        tenant_id,
        to,
        subject,
        body,
        ics,
        status,
        error,
    )
    return {"email_id": str(eid), "status": status, "to": to}


async def slack(webhook_url: str, text: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(webhook_url, json={"text": text})
        r.raise_for_status()
    return {"slack": "posted"}


async def hubspot_upsert(token: str, props: dict[str, Any]) -> dict:
    """Create the contact in HubSpot; an existing email (409) counts as already synced."""
    clean = {k: str(v) for k, v in props.items() if v not in (None, "")}
    async with httpx.AsyncClient(timeout=15, headers={"Authorization": f"Bearer {token}"}) as client:
        r = await client.post("https://api.hubapi.com/crm/v3/objects/contacts", json={"properties": clean})
        if r.status_code == 409:
            return {"hubspot": "exists"}
        r.raise_for_status()
        return {"hubspot": r.json().get("id")}


async def post_webhook(url: str, secret: str, payload: dict[str, Any]) -> dict:
    if not url.startswith("https://") and not url.startswith("http://localhost"):
        raise ValueError("webhook URL must be https")
    body = json.dumps(payload, default=str).encode()
    ts, sig = sign_payload(secret, body)
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-AgentGrid-Timestamp": ts,
                "X-AgentGrid-Signature": sig,
            },
        )
        r.raise_for_status()
    return {"status": r.status_code}
