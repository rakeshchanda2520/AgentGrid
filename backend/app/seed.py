"""Demo data: `python -m app.seed` (only if empty) or `python -m app.seed --reset` (wipe and recreate).

One agency (GrowthPilot Digital, white-labeled as "GrowthPilot AI") with two clients:
  Skyline Realty  → agent "Aria" (real-estate lead qualifier), key pk_skyline_aria
  BrightSmile Dental Clinic → agent "Mia" (healthcare clinic), key pk_brightsmile_mia
plus 30 days of synthetic conversation history so the dashboards are populated. All data is fictional.
"""

import asyncio
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import asyncpg

from app import db, jobs, rag, workflows  # noqa: F401  (rag/workflows register job handlers)
from app.agent import scoring
from app.api.admin import create_agent
from app.config import settings
from app.security import hash_password

DATA = Path(__file__).parent / "seed_data"
TZ_NOTE = "Asia/Kolkata"

SKYLINE_PROFILE = """Skyline Realty, Bengaluru. Projects: Orchid Heights (Whitefield, 2/3 BHK), Lakeview (Hebbal, 3/4 BHK premium),
Greens Villas (Sarjapur Road, 4 BHK villas), Commercial Hub (Whitefield offices). Sales office: Skyline Experience Centre, Indiranagar.
Phone +91 80 4000 1234. Site visits Mon-Sat."""
BRIGHTSMILE_PROFILE = """BrightSmile Dental Clinic, Koramangala 4th Block, Bengaluru. Dentists: Dr. Kavya Rao (orthodontics), Dr. Arjun Menon
(endodontics), Dr. Sneha Iyer (general and cosmetic). Phone +91 80 4111 2233. Open Mon-Fri 9-6, Sat 9-2."""

SKYLINE_CATALOG = [
    (
        "Orchid Heights 2 BHK, Tower A",
        "Ready to move in, east facing, 1,180 sq ft, 9th floor, park view.",
        9_200_000,
        {"location": "Whitefield", "type": "apartment", "bedrooms": 2, "tags": ["ready", "metro"]},
    ),
    (
        "Orchid Heights 2 BHK, Tower C",
        "Under construction, possession Dec 2027, 1,260 sq ft, construction-linked plan.",
        9_600_000,
        {"location": "Whitefield", "type": "apartment", "bedrooms": 2, "tags": ["under construction"]},
    ),
    (
        "Orchid Heights 3 BHK, Tower B",
        "Ready to move in, 1,620 sq ft corner unit, two balconies, pool view.",
        12_800_000,
        {"location": "Whitefield", "type": "apartment", "bedrooms": 3, "tags": ["ready", "corner", "metro"]},
    ),
    (
        "Orchid Heights 3 BHK, Tower D",
        "Possession Dec 2027, 1,780 sq ft, high floor, customisable interiors.",
        13_900_000,
        {"location": "Whitefield", "type": "apartment", "bedrooms": 3, "tags": ["under construction", "high floor"]},
    ),
    (
        "Lakeview 3 BHK",
        "Lake-facing premium apartment, 1,850 sq ft, possession June 2027, subvention plan.",
        21_500_000,
        {"location": "Hebbal", "type": "apartment", "bedrooms": 3, "tags": ["lake view", "premium", "airport"]},
    ),
    (
        "Lakeview 4 BHK",
        "2,450 sq ft, only 4 homes per floor, sky lounge access, possession June 2027.",
        29_500_000,
        {"location": "Hebbal", "type": "apartment", "bedrooms": 4, "tags": ["lake view", "premium"]},
    ),
    (
        "Greens Villa, Phase 1",
        "Ready 4 BHK villa, 2,900 sq ft on a 2,400 sq ft plot with private garden.",
        34_000_000,
        {"location": "Sarjapur Road", "type": "villa", "bedrooms": 4, "tags": ["ready", "garden", "schools"]},
    ),
    (
        "Greens Villa, Phase 2",
        "4 BHK villa, 3,400 sq ft, possession March 2027, stamp duty waiver offer.",
        37_500_000,
        {"location": "Sarjapur Road", "type": "villa", "bedrooms": 4, "tags": ["offer", "garden", "schools"]},
    ),
    (
        "Commercial Hub office, 600 sq ft",
        "Pre-leased office space with 7.5% expected rental yield.",
        7_800_000,
        {"location": "Whitefield", "type": "commercial", "tags": ["investment", "pre-leased"]},
    ),
]
BRIGHTSMILE_CATALOG = [
    (
        "New patient check-up",
        "Full examination with digital X-ray and a personalised plan.",
        800,
        {"tags": ["check-up", "checkup", "first", "consultation", "pain", "toothache"]},
    ),
    ("Cleaning and polishing", "Scaling and polishing, recommended every 6 months.", 1500, {"tags": ["cleaning", "stains", "gums", "polishing"]}),
    ("Family check-up package", "Check-up for up to 4 family members.", 2400, {"tags": ["family", "children", "kids", "check-up"]}),
    (
        "In-clinic teeth whitening",
        "60-minute professional whitening, results last 12-24 months.",
        12000,
        {"tags": ["whitening", "stains", "wedding", "cosmetic", "smile"]},
    ),
    ("Take-home whitening kit", "Custom trays with professional gel, gradual whitening at home.", 7500, {"tags": ["whitening", "home", "cosmetic"]}),
    ("Metal braces", "Full orthodontic treatment, 12 to 18 months.", 45000, {"tags": ["braces", "crooked", "alignment", "orthodontic"]}),
    ("Clear aligners", "Invisible aligners with free 3D scan assessment.", 120000, {"tags": ["aligners", "braces", "invisible", "crooked", "alignment"]}),
    (
        "Root canal treatment (molar)",
        "Single-sitting root canal where possible, by our endodontist.",
        8500,
        {"tags": ["root canal", "pain", "toothache", "infection"]},
    ),
    ("Dental implant with crown", "Permanent tooth replacement, from ₹38,000 per tooth.", 38000, {"tags": ["implant", "missing tooth", "replacement"]}),
]

FIRST = [
    "Rahul",
    "Priya",
    "Arjun",
    "Sneha",
    "Vikram",
    "Ananya",
    "Karthik",
    "Divya",
    "Rohan",
    "Meera",
    "Aditya",
    "Kavya",
    "Sanjay",
    "Pooja",
    "Nikhil",
    "Isha",
    "Manish",
    "Lakshmi",
    "Varun",
    "Neha",
    "Suresh",
    "Asha",
    "Imran",
    "Fatima",
    "John",
    "Grace",
]
LAST = ["Sharma", "Iyer", "Reddy", "Nair", "Gupta", "Menon", "Rao", "Kumar", "Shetty", "Patel", "Khan", "Joseph", "Das", "Pillai"]

SKY_TALK = [
    (
        "Hi, I'm looking for a 3BHK in Whitefield",
        "Orchid Heights in Whitefield has 3 BHK homes from ₹1.28 crore, with Towers A and B ready to move in [S1]. What budget do you have in mind?",
    ),
    (
        "What is the price of Lakeview 4 BHK?",
        "Lakeview 4 BHK homes start at ₹2.95 crore, with possession in June 2027 [S1]. Would you like to see the floor plans on a site visit?",
    ),
    ("Is there a metro near Orchid Heights?", "Yes, Kadugodi Tree Park metro station is 1.2 km away, about 4 minutes by car [S1]."),
    (
        "Budget around 1 crore, planning in 3 months, home loan pre-approved",
        "Thanks! With a budget near ₹1 crore, the Orchid Heights 2 BHK in Tower A (ready, ₹92 L) is a strong fit. Shall I book a site visit?",
    ),
    ("Do you have villas near good schools?", "Skyline Greens Villas on Sarjapur Road are near Inventure Academy and Greenwood High, from ₹3.4 crore [S1]."),
    (
        "What payment plans do you have?",
        "We offer a construction-linked plan, a down payment plan with a 4% discount, and a subvention plan for Lakeview [S1].",
    ),
    ("Book a site visit for Saturday", "Here are Saturday slots: 1) 10:00 AM 2) 12:00 PM. Reply with the option number."),
    ("Is it RERA approved?", "Yes, every Skyline project is registered with Karnataka RERA [S1]."),
    ("Can NRIs buy?", "Yes. NRIs can buy and we help with power of attorney and NRE/NRO payments [S1]."),
]
BS_TALK = [
    ("How much is teeth whitening?", "Professional in-clinic whitening is ₹12,000 for a 60-minute session [S1]. Would you like to book a consultation first?"),
    ("Do you do braces for adults?", "Yes. Metal braces are ₹45,000 and clear aligners start at ₹1,20,000, with a free 3D scan [S1]."),
    ("I want to book a cleaning", "Cleaning and polishing is ₹1,500 [S1]. Here are some slots: 1) Mon 10:00 AM 2) Mon 12:00 PM. Which works?"),
    ("Are you open on Sunday?", "We're closed on Sundays. We're open Mon-Fri 9 AM to 6 PM and Sat 9 AM to 2 PM [S1]."),
    ("How much is a root canal?", "Root canal treatment is ₹6,500 for front teeth and ₹8,500 for molars [S1]."),
    ("Do you treat kids?", "Yes, from age 3. Dr. Sneha Iyer sees most of our young patients [S1]."),
    ("Do you accept insurance?", "We aren't empanelled for cashless insurance, but we give itemised bills for reimbursement [S1]."),
]


async def wipe(conn: asyncpg.Connection) -> None:
    await conn.execute("""truncate tenants, users, jobs, refresh_tokens, audit_logs cascade""")


async def _users(c, agency: UUID, sky: UUID, bs: UUID) -> list[tuple[str, str]]:
    pw = hash_password(settings().demo_password)
    people = [
        ("admin@agentgrid.demo", "Platform Admin", True, []),
        ("agency@growthpilot.demo", "Gauri Pillai (GrowthPilot)", False, [(agency, "agency_admin")]),
        ("owner@skyline.demo", "Ravi Kulkarni (Skyline)", False, [(sky, "client_admin")]),
        ("agent@skyline.demo", "Neha Joseph (Skyline sales)", False, [(sky, "human_agent")]),
        ("viewer@skyline.demo", "Skyline Viewer", False, [(sky, "viewer")]),
        ("owner@brightsmile.demo", "Dr. Kavya Rao (BrightSmile)", False, [(bs, "client_admin")]),
        ("agent@brightsmile.demo", "Asha Das (BrightSmile front desk)", False, [(bs, "human_agent")]),
    ]
    out = []
    for email, name, plat, roles in people:
        uid = await c.fetchval("insert into users (email, name, password_hash, is_platform_admin) values ($1,$2,$3,$4) returning id", email, name, pw, plat)
        for tid, role in roles:
            await c.execute("insert into memberships (user_id, tenant_id, role) values ($1,$2,$3)", uid, tid, role)
        out.append((email, roles[0][1] if roles else "platform_admin"))
    return out


async def _knowledge(c, tenant: UUID, agent: UUID, folder: str) -> None:
    for f in sorted((DATA / folder).glob("*.md")):
        title = f.stem.replace("_", " ").title()
        sid = await c.fetchval(
            "insert into knowledge_sources (tenant_id, agent_id, type, title, uri, raw_text) values ($1,$2,'file',$3,$4,$5) returning id",
            tenant,
            agent,
            title,
            f.name,
            f.read_text(encoding="utf-8"),
        )
        await jobs.enqueue(c, "kb.ingest", {"source_id": str(sid)}, tenant)


async def _history(c, tenant: UUID, agent: dict, kind: str, n: int, staff: UUID, rng: random.Random) -> None:
    """Synthetic past conversations (fictional people) so analytics have shape on first open."""
    talk = SKY_TALK if kind == "sky" else BS_TALK
    qual = agent["config"]["qualification"]
    now = datetime.now(UTC)
    services = agent["config"]["booking"]["services"]
    slot_cursor = now - timedelta(days=29)
    for i in range(n):
        started = now - timedelta(days=rng.uniform(0, 30), hours=rng.uniform(0, 8))
        channel = rng.choices(["web", "whatsapp", "telegram", "api"], [50, 30, 15, 5])[0]
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        contact = await c.fetchval(
            "insert into contacts (tenant_id, channel, channel_user_id, name, created_at) values ($1,$2,$3,$4,$5) returning id",
            tenant,
            channel,
            f"hist-{kind}-{i}",
            name,
            started,
        )
        escalated = rng.random() < 0.18
        human = escalated and rng.random() < 0.85
        resolved = rng.random() < 0.9
        frt = int(rng.gauss(1700, 450))
        conv = await c.fetchval(
            """insert into conversations (tenant_id, agent_id, contact_id, channel, state, escalated, human_replied, first_response_ms, csat,
                 started_at, last_message_at, resolved_at, outcome, assigned_user_id)
               values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) returning id""",
            tenant,
            agent["id"],
            contact,
            channel,
            "RESOLVED" if resolved else ("PENDING_HUMAN" if escalated else "BOT_ACTIVE"),
            escalated,
            human,
            max(600, frt),
            rng.choice([5, 5, 5, 5, 1]) if rng.random() < 0.4 else None,
            started,
            started + timedelta(minutes=8),
            started + timedelta(minutes=30) if resolved else None,
            "resolved" if resolved else None,
            staff if human else None,
        )
        await c.execute(
            "insert into analytics_events (tenant_id, type, agent_id, conversation_id, channel, ts) values ($1,'conversation.started',$2,$3,$4,$5)",
            tenant,
            agent["id"],
            conv,
            channel,
            started,
        )
        t = started
        for q, a in rng.sample(talk, k=rng.randint(1, 3)):
            await c.execute("insert into messages (tenant_id, conversation_id, role, content, created_at) values ($1,$2,'user',$3,$4)", tenant, conv, q, t)
            lat = int(rng.gauss(1600, 400))
            t += timedelta(milliseconds=max(500, lat))
            tin, tout = rng.randint(2200, 3400), rng.randint(60, 160)
            await c.execute(
                """insert into messages (tenant_id, conversation_id, role, content, model, provider, tokens_in, tokens_out, tokens_cached, cost_usd, latency_ms, created_at)
                   values ($1,$2,'assistant',$3,'openrouter:anthropic/claude-sonnet-4.5','platform',$4,$5,$6,$7,$8,$9)""",
                tenant,
                conv,
                a,
                tin,
                tout,
                int(tin * 0.7),
                round(tin / 1e6 * 3 * 0.4 + tout / 1e6 * 15, 6),
                max(500, lat),
                t,
            )
            t += timedelta(seconds=rng.randint(20, 90))
        if human:
            await c.execute(
                "insert into messages (tenant_id, conversation_id, role, content, author_id, created_at) values ($1,$2,'human',$3,$4,$5)",
                tenant,
                conv,
                "Hi, this is the team. Happy to help you personally. Let me call you shortly.",
                staff,
                t,
            )
        # lead
        roll = rng.random()
        fields: dict = {}
        if kind == "sky":
            pool = {
                "intent": rng.choice(["buy", "buy", "invest"]),
                "location": rng.choice(["Whitefield", "Hebbal", "Sarjapur Road"]),
                "budget": rng.choice([9_000_000, 12_000_000, 15_000_000, 25_000_000, 35_000_000]),
                "property_type": rng.choice(["apartment", "villa"]),
                "bedrooms": rng.choice([2, 3, 4]),
                "timeline_months": rng.choice([1, 3, 6, 12]),
                "financing": rng.choice(["loan", "loan_preapproved", "cash"]),
                "name": name,
                "phone": f"+91 9{rng.randint(100000000, 999999999)}",
            }
        else:
            pool = {
                "concern": rng.choice(["whitening", "cleaning", "braces", "root canal", "check-up"]),
                "new_patient": rng.random() < 0.6,
                "preferred_date": rng.choice(["this week", "Saturday morning", "next Monday"]),
                "name": name,
                "phone": f"+91 9{rng.randint(100000000, 999999999)}",
                "email": f"{name.split()[0].lower()}@example.com",
            }
        keys = list(pool)
        take = 0 if roll < 0.25 else rng.randint(2, len(keys))
        fields = {k: pool[k] for k in keys[:take]}
        if fields:
            pts, stage, _ = scoring.score(fields, qual)
            booked = stage in ("qualified", "hot") and rng.random() < 0.45
            lead = await c.fetchval(
                """insert into leads (tenant_id, agent_id, contact_id, conversation_id, fields, score, stage, source_channel, created_at, updated_at)
                   values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9) returning id""",
                tenant,
                agent["id"],
                contact,
                conv,
                fields,
                pts,
                "booked" if booked else stage,
                channel,
                started,
            )
            await c.execute("update contacts set name = coalesce($2, name), phone = $3 where id = $1", contact, fields.get("name"), fields.get("phone"))
            if booked:
                slot_cursor += timedelta(hours=rng.choice([3, 5, 7]))
                svc = services[0] if kind == "sky" else rng.choice(services)
                await c.execute(
                    """insert into appointments (tenant_id, agent_id, contact_id, conversation_id, service, starts_at, ends_at, status, customer_name, customer_contact, created_at)
                       values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
                    tenant,
                    agent["id"],
                    contact,
                    conv,
                    svc["name"],
                    slot_cursor,
                    slot_cursor + timedelta(minutes=svc["minutes"]),
                    "completed" if slot_cursor < now else "booked",
                    name,
                    fields.get("phone"),
                    started,
                )
            if stage in ("qualified", "hot"):
                await c.execute(
                    "insert into analytics_events (tenant_id, type, agent_id, conversation_id, channel, props, ts) values ($1,'lead.qualified',$2,$3,$4,$5,$6)",
                    tenant,
                    agent["id"],
                    conv,
                    channel,
                    {"lead_id": str(lead), "score": pts},
                    started,
                )


async def seed() -> list[tuple[str, str]]:
    rng = random.Random(42)
    async with db.tx(system=True) as c:
        platform = await c.fetchval("insert into tenants (kind, name, slug) values ('platform','AgentGrid','agentgrid') returning id")
        agency = await c.fetchval(
            """insert into tenants (parent_id, kind, name, slug, settings, branding) values ($1,'agency','GrowthPilot Digital','growthpilot',$2,$3) returning id""",
            platform,
            {"timezone": TZ_NOTE, "sales_email": "hello@growthpilot.demo"},
            {
                "product_name": "GrowthPilot AI",
                "primary_color": "#123C46",
                "accent_color": "#E59A3A",
                "support_email": "help@growthpilot.demo",
                "hide_powered_by": False,
            },
        )
        sky = await c.fetchval(
            "insert into tenants (parent_id, kind, name, slug, settings, branding) values ($1,'client','Skyline Realty','skyline',$2,$3) returning id",
            agency,
            {"timezone": TZ_NOTE, "sales_email": "sales@skyline.demo", "retention_days": 90},
            {"primary_color": "#1E3A5F", "accent_color": "#C8963E", "widget_title": "Skyline Realty"},
        )
        bs = await c.fetchval(
            "insert into tenants (parent_id, kind, name, slug, settings, branding) values ($1,'client','BrightSmile Dental Clinic','brightsmile',$2,$3) returning id",
            agency,
            {"timezone": TZ_NOTE, "sales_email": "frontdesk@brightsmile.demo", "retention_days": 90},
            {"primary_color": "#0E5E6F", "accent_color": "#F2A541", "widget_title": "BrightSmile Dental"},
        )
        users = await _users(c, agency, sky, bs)
        aria = await create_agent(c, sky, "Aria", "real_estate", public_key="pk_skyline_aria", business_profile=SKYLINE_PROFILE)
        mia = await create_agent(c, bs, "Mia", "healthcare_clinic", public_key="pk_brightsmile_mia", business_profile=BRIGHTSMILE_PROFILE)
        for tenant, agent, items in ((sky, aria, SKYLINE_CATALOG), (bs, mia, BRIGHTSMILE_CATALOG)):
            for name, desc, price, attrs in items:
                await c.execute(
                    "insert into catalog_items (tenant_id, agent_id, name, description, price, attributes) values ($1,$2,$3,$4,$5,$6)",
                    tenant,
                    agent["id"],
                    name,
                    desc,
                    price,
                    attrs,
                )
        await _knowledge(c, sky, aria["id"], "skyline")
        await _knowledge(c, bs, mia["id"], "brightsmile")
        staff = {r["email"]: r["id"] for r in await c.fetch("select id, email from users")}
        await _history(c, sky, aria, "sky", 120, staff["agent@skyline.demo"], rng)
        await _history(c, bs, mia, "bs", 90, staff["agent@brightsmile.demo"], rng)
        await c.execute(
            """insert into usage_daily (tenant_id, day, model, messages, tokens_in, tokens_out, cost_usd)
               select m.tenant_id, m.created_at::date, m.model, count(*), sum(m.tokens_in), sum(m.tokens_out), sum(m.cost_usd)
               from messages m where m.role = 'assistant' group by 1, 2, 3"""
        )
        await c.execute(
            """insert into analytics_events (tenant_id, type, agent_id, conversation_id, channel, props, ts)
               select tenant_id, 'conversation.escalated', agent_id, id, channel, '{"reason": "customer asked for a person"}', started_at + interval '5 minutes'
               from conversations where escalated"""
        )
    await jobs.drain()  # ingest knowledge now so the agents can answer immediately
    return users


async def seed_if_empty() -> None:
    async with db.tx(system=True) as c:
        if await c.fetchval("select count(*) from tenants"):
            return
    users = await seed()
    print(f"Seeded demo data. Password for every demo user: (DEMO_PASSWORD). Users: {', '.join(u for u, _ in users)}")


async def _main() -> None:
    await db.migrate()
    if "--reset" in sys.argv:
        conn = await asyncpg.connect(settings().database_url)
        await wipe(conn)
        await conn.close()
        await seed()
        print("Demo data recreated.")
    else:
        await seed_if_empty()
    await db.close()


if __name__ == "__main__":
    asyncio.run(_main())
