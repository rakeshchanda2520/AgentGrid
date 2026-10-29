"""End-to-end conversation flows through the real pipeline (LangGraph + tools + DB + jobs) with the offline model."""

from app import conversations, db, jobs


async def say(tenant, agent, user, text, channel="web"):
    res = await conversations.inbound(tenant, agent, channel, user, text, auto_reply=False)
    turn = await conversations.reply_now(tenant, res["conversation_id"])
    return res["conversation_id"], turn


async def test_rag_answer_cites_source(ids):
    sky, aria = ids["tenants"]["skyline"], ids["agents"]["pk_skyline_aria"]
    _, turn = await say(sky, aria, "flow-rag", "Is there a metro near Orchid Heights?")
    assert "1.2 km" in turn["reply"] and turn["citations"], turn["reply"]
    assert turn["trace"]["path"][:2] == ["guard_in", "agent"]


async def test_off_topic_twice_hands_over(ids):
    sky, aria = ids["tenants"]["skyline"], ids["agents"]["pk_skyline_aria"]
    _, first = await say(sky, aria, "flow-offtopic", "What is the capital of France?")
    assert "not certain" in first["reply"] and first["state"] == "BOT_ACTIVE"
    conv, second = await say(sky, aria, "flow-offtopic", "And who won the 1998 football world cup?")
    assert second["state"] == "PENDING_HUMAN"
    async with db.tx([sky]) as c:
        row = await c.fetchrow("select state, summary from conversations where id = $1", conv)
    assert row["state"] == "PENDING_HUMAN" and row["summary"]["bullets"]


async def test_qualify_book_and_workflows(ids):
    sky, aria = ids["tenants"]["skyline"], ids["agents"]["pk_skyline_aria"]
    conv, t1 = await say(
        sky,
        aria,
        "flow-book",
        "I'm Rahul Mehta, want to buy a 3 BHK apartment in Whitefield, budget 1.4 crore, in 2 months, home loan pre-approved. Call 9876543210",
    )
    lead = t1["trace"]["lead"]
    assert lead["stage"] in ("qualified", "hot"), t1
    assert lead["fields"]["phone"] == "9876543210"  # tools resolve the placeholder server-side
    async with db.tx([sky]) as c:
        stored = await c.fetchval("select string_agg(content, ' ') from messages where conversation_id = $1", conv)
    assert "9876543210" not in stored  # transcripts and the LLM only ever see <PHONE_1>
    _, t2 = await say(sky, aria, "flow-book", "Can I book a site visit?")
    assert "1)" in t2["reply"], t2["reply"]
    _, t3 = await say(sky, aria, "flow-book", "option 1")
    assert "Booked" in t3["reply"], t3["reply"]
    await jobs.drain()
    async with db.tx([sky]) as c:
        appt = await c.fetchrow("select * from appointments where conversation_id = $1", conv)
        stage = await c.fetchval("select stage from leads where conversation_id = $1", conv)
        emails = await c.fetch("select subject from outbox_emails where tenant_id = $1 and created_at > now() - interval '5 minutes'", sky)
        runs = await c.fetch("select status from workflow_runs where tenant_id = $1 and created_at > now() - interval '5 minutes'", sky)
    assert appt and stage == "booked"
    assert any("Site visit confirmed" in e["subject"] for e in emails) and any("qualified lead" in e["subject"] for e in emails)
    assert runs and all(r["status"] in ("succeeded", "running", "stopped") for r in runs)

    # the same slot cannot be booked twice
    other, t4 = await say(sky, aria, "flow-book-2", "book a site visit")
    async with db.tx([sky]) as c:
        await c.execute(
            "update conversations set memory = jsonb_build_object('offered_slots', $2::jsonb) where id = $1",
            other,
            [{"iso": appt["starts_at"].isoformat(), "label": "taken", "service": "site_visit"}],
        )
    _, t5 = await say(sky, aria, "flow-book-2", "option 1")
    assert any("just taken" in r["result"] for r in t5["trace"]["tool_results"]), t5["trace"]["tool_results"]


async def test_handover_keyword_and_human_reply(ids):
    bs, mia = ids["tenants"]["brightsmile"], ids["agents"]["pk_brightsmile_mia"]
    conv, t = await say(bs, mia, "flow-human", "I want to talk to a person please")
    assert t["state"] == "PENDING_HUMAN" and t["trace"]["path"] == ["guard_in", "handover"]
    async with db.tx(system=True) as c:
        staff = await c.fetchval("select id from users where email = 'agent@brightsmile.demo'")
    await conversations.human_reply(bs, {bs}, conv, staff, "Hi, Asha here from the front desk.")
    _, after = await say(bs, mia, "flow-human", "thanks")
    assert after is None  # bot stays silent while a human owns the conversation


async def test_sensitive_topic_escalates(ids):
    bs, mia = ids["tenants"]["brightsmile"], ids["agents"]["pk_brightsmile_mia"]
    _, t = await say(bs, mia, "flow-sensitive", "I have severe pain and swelling since last night")
    assert t["state"] == "PENDING_HUMAN" and "sensitive" in t["trace"]["handover"]


async def test_recommendations(ids):
    sky, aria = ids["tenants"]["skyline"], ids["agents"]["pk_skyline_aria"]
    _, t = await say(sky, aria, "flow-reco", "Can you recommend a villa near schools on Sarjapur Road?")
    assert "Greens Villa" in t["reply"], t["reply"]


async def test_duplicate_webhook_is_ignored(ids):
    sky, aria = ids["tenants"]["skyline"], ids["agents"]["pk_skyline_aria"]
    a = await conversations.inbound(sky, aria, "whatsapp", "919800000001", "hello", external_id="wa:dup-1", auto_reply=False)
    b = await conversations.inbound(sky, aria, "whatsapp", "919800000001", "hello", external_id="wa:dup-1", auto_reply=False)
    assert "message_id" in a and b.get("duplicate")
