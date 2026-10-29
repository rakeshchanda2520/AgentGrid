import json

from app import db
from app.agent.scoring import score
from app.conversations import detokenize, open_conversation, tokenize
from app.security import find_pii, sign_payload, verify_meta_signature
from app.templates import agent_config
from app.workflows import matches, render
from tests.conftest import login


def test_pii_detection():
    text = "I'm Rahul, call 98765 43210 or +91-9876543210, mail rahul@example.com, card 4111 1111 1111 1111, PAN ABCDE1234F"
    kinds = [k for _, _, k, _ in find_pii(text)]
    assert kinds.count("PHONE") == 2 and "EMAIL" in kinds and "CARD" in kinds and "PAN" in kinds
    assert not find_pii("Budget 12000000 for a 3 BHK, timeline 3 months")  # budgets are not phone numbers


async def test_tokenize_roundtrip_and_isolation(ids):
    sky = ids["tenants"]["skyline"]
    agent = ids["agents"]["pk_skyline_aria"]
    async with db.tx([sky]) as c:
        conv, _, _ = await open_conversation(c, sky, agent, "web", "pii-test-visitor")
        other, _, _ = await open_conversation(c, sky, agent, "web", "pii-test-other")
        masked = await tokenize(c, sky, conv["id"], "Call me on 9876543210 or 9876543210, email a@b.co")
        assert "9876543210" not in masked and masked.count("<PHONE_1>") == 2 and "<EMAIL_1>" in masked
        assert await detokenize(c, conv["id"], masked) == "Call me on 9876543210 or 9876543210, email a@b.co"
        assert await detokenize(c, other["id"], masked) == masked  # tokens never resolve in another conversation


async def test_rls_blocks_other_tenants(ids):
    sky, bs = ids["tenants"]["skyline"], ids["tenants"]["brightsmile"]
    async with db.tx([sky]) as c:
        assert await c.fetchval("select count(*) from conversations where tenant_id = $1", bs) == 0
        assert await c.fetchval("select count(*) from knowledge_chunks where tenant_id = $1", bs) == 0
        assert await c.fetchval("select count(*) from conversations") > 0
    async with db.tx([]) as c:  # no context → nothing visible
        assert await c.fetchval("select count(*) from leads") == 0


async def test_api_cross_tenant_returns_404(client, ids):
    async with db.tx(system=True) as c:
        bs_conv = await c.fetchval("select id from conversations where tenant_id = $1 limit 1", ids["tenants"]["brightsmile"])
    headers = await login(client, "owner@skyline.demo")
    assert (await client.get(f"/conversations/{bs_conv}", headers=headers)).status_code == 404
    forged = headers | {"X-Tenant-Id": str(ids["tenants"]["brightsmile"])}
    assert (await client.get("/conversations", headers=forged)).status_code == 403


async def test_rbac_viewer_cannot_change_agents(client, ids):
    headers = await login(client, "viewer@skyline.demo")
    r = await client.patch(f"/agents/{ids['agents']['pk_skyline_aria']}", json={"name": "x"}, headers=headers)
    assert r.status_code == 403


def test_lead_scoring():
    qual = agent_config("real_estate")["qualification"]
    pts, stage, missing = score({}, qual)
    assert (pts, stage) == (0, "new") and missing[0] == "intent"
    pts, stage, _ = score({"intent": "buy", "location": "Whitefield", "budget": 12000000, "timeline_months": 2, "property_type": "apartment"}, qual)
    assert (pts, stage) == (70, "qualified")
    pts, stage, _ = score(
        {"intent": "buy", "location": "Whitefield", "budget": 12000000, "timeline_months": 2, "property_type": "apartment", "financing": "loan_preapproved"},
        qual,
    )
    assert (pts, stage) == (80, "hot")
    slow, _, _ = score({"timeline_months": 12}, qual)
    fast, _, _ = score({"timeline_months": 2}, qual)
    assert fast > slow


def test_webhook_signatures():
    body = json.dumps({"x": 1}).encode()
    import hashlib
    import hmac

    good = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_meta_signature("secret", body, good)
    assert not verify_meta_signature("secret", body + b" ", good)
    assert not verify_meta_signature("secret", body, None)
    ts, sig = sign_payload("k", body, 1700000000)
    assert ts == "1700000000" and sig.startswith("sha256=")


def test_workflow_filters_and_templates():
    ctx = {"lead": {"score": 72, "stage": "qualified", "fields": {"name": "Asha"}}}
    assert matches(ctx, [{"field": "lead.score", "op": ">=", "value": 60}])
    assert not matches(ctx, [{"field": "lead.stage", "op": "==", "value": "booked"}])
    assert render("Hi {{ lead.fields.name or 'there' }} ({{ contact.email or 'none' }})", ctx) == "Hi Asha (none)"
    from jinja2.exceptions import SecurityError

    try:  # sandboxed: internals are either blanked or refused, never exposed
        out = render("{{ ''.__class__.__mro__[1].__subclasses__() }}", ctx)
    except SecurityError:
        out = ""
    assert "class" not in out
