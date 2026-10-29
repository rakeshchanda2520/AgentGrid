import hashlib
import hmac
import json

from app import channels, db, jobs
from app.security import encrypt
from tests.conftest import login


async def test_login_me_and_dashboard(client):
    headers = await login(client, "agency@growthpilot.demo")
    me = (await client.get("/auth/me", headers=headers)).json()
    assert {t["kind"] for t in me["tenants"]} == {"agency", "client"}
    agency = next(t for t in me["tenants"] if t["kind"] == "agency")
    rollup = (await client.get("/analytics/agency", headers=headers | {"X-Tenant-Id": str(agency["id"])})).json()
    assert len(rollup) == 2 and all(r["conversations"] > 0 for r in rollup)
    ov = (await client.get("/analytics/overview?days=30", headers=headers)).json()
    assert ov["kpis"]["conversations"] > 0 and ov["funnel"][0]["value"] >= ov["funnel"][-1]["value"]


async def test_bad_login_rejected(client):
    r = await client.post("/auth/login", json={"email": "owner@skyline.demo", "password": "wrong-password"})
    assert r.status_code == 401


async def test_api_channel_with_key(client, ids):
    headers = await login(client, "owner@skyline.demo")
    key = (await client.post("/api-keys", json={"name": "test"}, headers=headers)).json()["key"]
    r = await client.post(
        "/v1/messages",
        headers={"X-API-Key": key},
        json={"agent_id": str(ids["agents"]["pk_skyline_aria"]), "user_id": "crm-42", "text": "What home loan banks do you work with?"},
    )
    assert r.status_code == 200 and "HDFC" in r.json()["reply"], r.text
    other_agent = ids["agents"]["pk_brightsmile_mia"]
    r = await client.post("/v1/messages", headers={"X-API-Key": key}, json={"agent_id": str(other_agent), "user_id": "x", "text": "hi"})
    assert r.status_code == 404  # a key only reaches its own workspace's agents


async def test_whatsapp_webhook_signature_and_routing(client, ids):
    sky, aria = ids["tenants"]["skyline"], ids["agents"]["pk_skyline_aria"]
    async with db.tx([sky]) as c:
        cid = await c.fetchval(
            """insert into channel_connections (tenant_id, agent_id, type, external_id, secrets_enc, webhook_secret)
               values ($1,$2,'whatsapp','PNID-123',$3,'verify-me') returning id""",
            sky,
            aria,
            encrypt(sky, {"access_token": "t", "app_secret": "appsecret"}),
        )
    v = await client.get(f"/webhooks/whatsapp/{cid}", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"})
    assert v.text == "42"
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "PNID-123"},
                            "contacts": [{"wa_id": "919811112222", "profile": {"name": "Kiran"}}],
                            "messages": [{"from": "919811112222", "id": "wamid.1", "type": "text", "text": {"body": "Hi"}}],
                        }
                    }
                ]
            }
        ]
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"appsecret", body, hashlib.sha256).hexdigest()
    assert (await client.post(f"/webhooks/whatsapp/{cid}", content=body, headers={"X-Hub-Signature-256": "sha256=bad"})).status_code == 401
    assert (await client.post(f"/webhooks/whatsapp/{cid}", content=body, headers={"X-Hub-Signature-256": sig})).status_code == 200
    async with db.tx([sky]) as c:
        assert await c.fetchval("select count(*) from messages where external_id = 'wa:wamid.1'") == 1


def test_telegram_parse():
    upd = {"update_id": 1, "message": {"message_id": 7, "chat": {"id": 555}, "from": {"first_name": "Ana"}, "text": "/start"}}
    assert channels.parse_telegram(upd) == {"chat_id": "555", "name": "Ana", "text": "Hi", "id": "tg:555:7"}
    assert channels.parse_telegram({"update_id": 2, "message": {"message_id": 8, "chat": {"id": 1}, "photo": []}}) is None


async def test_failed_jobs_retry_then_dead(ids):
    calls = []

    @jobs.handler("test.fail")
    async def fail(payload, tenant_id):
        calls.append(1)
        raise RuntimeError("boom")

    async with db.tx(system=True) as c:
        jid = await jobs.enqueue(c, "test.fail", {}, ids["tenants"]["skyline"], max_attempts=2)
        await c.execute("update jobs set run_at = now() - interval '1 second' where id = $1", jid)
    await jobs.drain()
    async with db.tx(system=True) as c:
        await c.execute("update jobs set run_at = now() - interval '1 second' where id = $1", jid)
    await jobs.drain()
    async with db.tx(system=True) as c:
        status, attempts = await c.fetchrow("select status, attempts from jobs where id = $1", jid)
    assert (status, attempts, len(calls)) == ("dead", 2, 2)


async def test_graph_mermaid(client):
    m = (await client.get("/agents/graph")).json()["mermaid"]
    assert "guard_in" in m and "handover" in m and "tools" in m
