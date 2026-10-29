"""Agent tools (LangChain StructuredTools). Tenant/agent/conversation ids come from the server-side Turn
in RunnableConfig, never from model arguments: the model cannot reach another tenant's data."""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import asyncpg
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

from app import db, rag
from app.agent import scoring

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass
class Turn:
    tenant_id: UUID
    tenant: dict[str, Any]
    agent: dict[str, Any]
    conversation: dict[str, Any]
    contact: dict[str, Any]
    lead: dict[str, Any] | None
    tz: ZoneInfo
    now: datetime
    retrieved: dict[str, dict[str, Any]] = field(default_factory=dict)
    citations: list[dict[str, Any]] = field(default_factory=list)
    low_conf: bool = False
    handover_reason: str | None = None
    memory: dict[str, Any] = field(default_factory=dict)
    path: list[str] = field(default_factory=list)

    @property
    def config(self) -> dict[str, Any]:
        return self.agent["config"]


def turn_of(config: RunnableConfig) -> Turn:
    return config["configurable"]["turn"]


def money(v: float | None) -> str:
    if v is None:
        return "price on request"
    v = float(v)
    return f"₹{v / 1e7:.2f} Cr" if v >= 1e7 else f"₹{v / 1e5:.1f} L" if v >= 1e5 else f"₹{v:,.0f}"


# ---------------------------------------------------------------- knowledge


async def _search_knowledge(query: str, config: RunnableConfig) -> str:
    turn = turn_of(config)
    hits, confident = await rag.search(turn.tenant_id, turn.agent["id"], query)
    if not hits or not confident:
        turn.low_conf = True
        return "NO_RELEVANT_RESULTS: the knowledge base does not answer this. Say you are not sure and offer to connect a team member."
    lines = []
    for h in hits:
        label = f"S{len(turn.retrieved) + 1}"
        body = h["content"].split("\n", 1)[-1]
        turn.retrieved[label] = {"chunk_id": str(h["id"]), "title": h["title"], "page": h["page"], "snippet": body[:240]}
        page = f", p.{h['page']}" if h["page"] else ""
        lines.append(f"[{label}] ({h['title']}{page}) {body}")
    return "\n".join(lines)


# ---------------------------------------------------------------- leads


async def _apply_lead_fields(c: asyncpg.Connection, turn: Turn, fields: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    from app.conversations import detokenize
    from app.workflows import emit

    qual = turn.config["qualification"]
    real = {}
    for k, v in fields.items():
        if scoring.present(v):
            real[k] = await detokenize(c, turn.conversation["id"], v) if isinstance(v, str) else v
    lead = turn.lead
    merged = (lead["fields"] if lead else {}) | real
    pts, stage, missing = scoring.score(merged, qual)
    old_stage = lead["stage"] if lead else "new"
    if old_stage == "booked":
        stage = "booked"
    lead = db.row(
        await c.fetchrow(
            """insert into leads (tenant_id, agent_id, contact_id, conversation_id, fields, score, stage, source_channel)
           values ($1, $2, $3, $4, $5, $6, $7, $8)
           on conflict (conversation_id) do update set fields = $5, score = $6, stage = $7, updated_at = now()
           returning *""",
            turn.tenant_id,
            turn.agent["id"],
            turn.contact["id"],
            turn.conversation["id"],
            merged,
            pts,
            stage,
            turn.conversation["channel"],
        )
    )
    turn.lead = lead
    await c.execute(
        "update contacts set name = coalesce($2, name), phone = coalesce($3, phone), email = coalesce($4, email) where id = $1",
        turn.contact["id"],
        merged.get("name"),
        merged.get("phone"),
        merged.get("email"),
    )
    ids = {"lead_id": lead["id"], "contact_id": turn.contact["id"], "conversation_id": turn.conversation["id"]}
    common = {"agent_id": turn.agent["id"], "conversation_id": turn.conversation["id"], "channel": turn.conversation["channel"]}
    await emit(c, turn.tenant_id, "lead.updated", ids=ids, event={"score": pts, "stage": stage}, **common)
    if stage in ("qualified", "hot") and old_stage in ("new", "engaged"):
        await emit(c, turn.tenant_id, "lead.qualified", ids=ids, event={"score": pts, "stage": stage}, **common)
    return lead, missing


def _lead_model(qual: dict[str, Any]) -> type[BaseModel]:
    types = {"string": str, "number": float, "integer": int, "boolean": bool}
    defs: dict[str, Any] = {}
    for name, spec in qual["fields"].items():
        t: Any = Literal[tuple(spec["values"])] if spec.get("type") == "enum" else types.get(spec.get("type", "string"), str)
        defs[name] = (t | None, Field(default=None, description=spec.get("label", name)))
    return create_model("LeadFields", **defs)


async def _update_lead(config: RunnableConfig, **fields: Any) -> str:
    turn = turn_of(config)
    async with db.tx([turn.tenant_id]) as c:
        lead, missing = await _apply_lead_fields(c, turn, fields)
    return f"Saved. score={lead['score']} stage={lead['stage']} missing={','.join(missing)}"


# ---------------------------------------------------------------- recommendations


class RecommendArgs(BaseModel):
    location: str | None = Field(None, description="Preferred area, if known")
    budget: float | None = Field(None, description="Maximum budget as a plain number in INR")
    property_type: str | None = Field(None, description="apartment / villa / plot / commercial, if relevant")
    bedrooms: int | None = Field(None, description="Bedrooms (BHK), if relevant")
    concern: str | None = Field(None, description="Need or treatment the customer mentioned, if relevant")
    keywords: str | None = Field(None, description="Other words describing what they want")


async def _recommend_items(config: RunnableConfig, **prefs: Any) -> str:
    turn = turn_of(config)
    lead_fields = (turn.lead or {}).get("fields", {})
    prefs = {k: v for k, v in ({**lead_fields, **prefs}).items() if scoring.present(v)}
    async with db.tx([turn.tenant_id]) as c:
        items = db.rows(await c.fetch("select name, description, price, attributes from catalog_items where agent_id = $1", turn.agent["id"]))
    if not items:
        return "No catalog configured. Answer from the knowledge base instead."
    words = set(re.findall(r"[a-z]{4,}", " ".join(str(prefs.get(k, "")) for k in ("concern", "keywords", "need")).lower()))
    scored = []
    for it in items:
        a, s, why = it["attributes"] or {}, 0.0, []
        if (loc := prefs.get("location")) and a.get("location") and (loc.lower() in a["location"].lower() or a["location"].lower() in loc.lower()):
            s, _ = s + 3, why.append(f"in {a['location']}")
        if (b := prefs.get("budget")) and it["price"] is not None:
            p = float(it["price"])
            if p <= float(b):
                s, _ = s + 3, why.append("within budget")
            elif p <= 1.1 * float(b):
                s, _ = s + 1, why.append("slightly above budget")
            else:
                s -= 2
        if (pt := prefs.get("property_type")) and a.get("type") == pt:
            s, _ = s + 2, why.append(pt)
        if (bd := prefs.get("bedrooms")) and a.get("bedrooms") == int(bd):
            s, _ = s + 2, why.append(f"{bd} BHK")
        text = f"{it['name']} {it['description']} {' '.join(a.get('tags', []))}".lower()
        hits = [w for w in words if w in text][:3]
        if hits:
            s, _ = s + len(hits), why.append("matches " + ", ".join(hits))
        scored.append((s, it, why))
    scored.sort(key=lambda x: (-x[0], float(x[1]["price"] or 0)))
    top = [x for x in scored if x[0] > 0][:3] or scored[:3]
    turn.memory["last_recommendations"] = [t[1]["name"] for t in top]
    label = turn.config.get("recommendation", {}).get("label", "options")
    lines = [f"Here are {len(top)} {label} that fit:"]
    for i, (_, it, why) in enumerate(top, 1):
        loc = f" | {it['attributes'].get('location')}" if it["attributes"].get("location") else ""
        lines.append(f"{i}. {it['name']}: {money(it['price'])}{loc}. {it['description'][:110]}" + (f" ({'; '.join(why)})" if why else ""))
    return "\n".join(lines)


# ---------------------------------------------------------------- booking


def _service(turn: Turn, key: str | None) -> dict[str, Any]:
    services = turn.config["booking"]["services"]
    if key:
        k = key.lower()
        for s in services:
            if k in (s["key"], s["name"].lower()) or k in s["name"].lower():
                return s
    return services[0]


def _label(dt: datetime) -> str:
    return dt.strftime("%a %d %b, %I:%M %p").replace(" 0", " ")


async def _booked(c: asyncpg.Connection, agent_id: UUID, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    rs = await c.fetch(
        "select starts_at, ends_at from appointments where agent_id = $1 and status = 'booked' and starts_at < $3 and ends_at > $2",
        agent_id,
        start,
        end,
    )
    return [(r["starts_at"], r["ends_at"]) for r in rs]


def _parse_day(s: str | None, fallback: date) -> date:
    try:
        return date.fromisoformat(str(s)[:10]) if s else fallback
    except ValueError:
        return fallback


async def _check_availability(config: RunnableConfig, date_from: str | None = None, date_to: str | None = None, service: str | None = None) -> str:
    turn = turn_of(config)
    svc = _service(turn, service)
    today = turn.now.astimezone(turn.tz).date()
    start = max(_parse_day(date_from, today), today)
    end = min(max(_parse_day(date_to, start + timedelta(days=3)), start), start + timedelta(days=7))
    hours = turn.config["booking"]["hours"]
    dur = timedelta(minutes=svc["minutes"])
    earliest = turn.now + timedelta(hours=1)
    async with db.tx([turn.tenant_id]) as c:
        taken = await _booked(c, turn.agent["id"], datetime.combine(start, time(0), turn.tz), datetime.combine(end + timedelta(days=1), time(0), turn.tz))
    slots: list[datetime] = []
    d = start
    while d <= end and len(slots) < 6:
        span = hours.get(DAYS[d.weekday()]) or ""
        if "-" in span:
            o, cl = (time.fromisoformat(x.strip()) for x in span.split("-"))
            t, close = datetime.combine(d, o, turn.tz), datetime.combine(d, cl, turn.tz)
            per_day = 0
            while t + dur <= close and per_day < 2:
                if t >= earliest and not any(t < e and t + dur > s for s, e in taken):
                    slots.append(t)
                    per_day += 1
                    t += timedelta(hours=2)  # spread the options across the day
                else:
                    t += dur
        d += timedelta(days=1)
    if not slots:
        return f"No free {svc['name']} slots between {start} and {end}. Offer other dates or a callback."
    turn.memory["offered_slots"] = [{"iso": s.isoformat(), "label": _label(s), "service": svc["key"]} for s in slots]
    lines = [f"Available {svc['name']} slots ({turn.tz.key}):"] + [f"{i}) {_label(s)}" for i, s in enumerate(slots, 1)]
    return "\n".join(lines) + "\nReply with the option number that suits you."


def _resolve_slot(turn: Turn, slot: str) -> tuple[datetime | None, str | None]:
    offered = turn.memory.get("offered_slots") or turn.conversation.get("memory", {}).get("offered_slots") or []
    s = slot.strip().lower()
    if m := re.fullmatch(r"(?:option|slot|#)?\s*(\d)", s):
        i = int(m.group(1)) - 1
        if 0 <= i < len(offered):
            return datetime.fromisoformat(offered[i]["iso"]), offered[i]["service"]
        return None, None
    for o in offered:
        if s in o["label"].lower() or o["label"].lower() in s or s.startswith(o["iso"][:16].lower()):
            return datetime.fromisoformat(o["iso"]), o["service"]
    try:
        dt = datetime.fromisoformat(slot.strip())
        return (dt if dt.tzinfo else dt.replace(tzinfo=turn.tz)), None
    except ValueError:
        return None, None


async def _book_appointment(
    config: RunnableConfig, slot: str, service: str | None = None, name: str | None = None, phone: str | None = None, email: str | None = None
) -> str:
    from app.workflows import emit

    turn = turn_of(config)
    start, offered_service = _resolve_slot(turn, slot)
    if not start:
        return "Could not identify that slot. Call check_availability and ask the customer to pick an option number."
    if start <= turn.now:
        return "That time is in the past. Offer future slots with check_availability."
    svc = _service(turn, service or offered_service)
    end = start + timedelta(minutes=svc["minutes"])
    async with db.tx([turn.tenant_id]) as c:
        extra = {k: v for k, v in {"name": name, "phone": phone, "email": email}.items() if v}
        if extra:
            await _apply_lead_fields(c, turn, extra)
        lf = (turn.lead or {}).get("fields", {})
        try:
            appt = await c.fetchrow(
                """insert into appointments (tenant_id, agent_id, contact_id, conversation_id, service, starts_at, ends_at, customer_name, customer_contact)
                   values ($1,$2,$3,$4,$5,$6,$7,$8,$9) returning id""",
                turn.tenant_id,
                turn.agent["id"],
                turn.contact["id"],
                turn.conversation["id"],
                svc["name"],
                start,
                end,
                lf.get("name") or turn.contact.get("name"),
                lf.get("phone") or lf.get("email") or turn.contact.get("phone"),
            )
        except asyncpg.exceptions.ExclusionViolationError:
            return "That slot was just taken. Apologise and offer the other options (call check_availability again)."
        if turn.lead:
            await c.execute("update leads set stage = 'booked', updated_at = now() where id = $1", turn.lead["id"])
        await emit(
            c,
            turn.tenant_id,
            "appointment.booked",
            ids={
                "appointment_id": appt["id"],
                "lead_id": (turn.lead or {}).get("id"),
                "contact_id": turn.contact["id"],
                "conversation_id": turn.conversation["id"],
            },
            event={"service": svc["name"], "starts_at": start.isoformat()},
            agent_id=turn.agent["id"],
            conversation_id=turn.conversation["id"],
            channel=turn.conversation["channel"],
        )
    turn.memory.pop("offered_slots", None)
    return f"Booked: {svc['name']} on {_label(start.astimezone(turn.tz))}. A confirmation will be sent."


async def _latest_booking(c: asyncpg.Connection, turn: Turn) -> asyncpg.Record | None:
    return await c.fetchrow(
        """select * from appointments where agent_id = $1 and contact_id = $2 and status = 'booked' and starts_at > now()
           order by starts_at limit 1""",
        turn.agent["id"],
        turn.contact["id"],
    )


async def _cancel_appointment(config: RunnableConfig) -> str:
    from app.workflows import emit

    turn = turn_of(config)
    async with db.tx([turn.tenant_id]) as c:
        appt = await _latest_booking(c, turn)
        if not appt:
            return "This customer has no upcoming booking."
        await c.execute("update appointments set status = 'cancelled' where id = $1", appt["id"])
        await emit(
            c,
            turn.tenant_id,
            "appointment.cancelled",
            ids={"appointment_id": appt["id"], "conversation_id": turn.conversation["id"]},
            agent_id=turn.agent["id"],
            conversation_id=turn.conversation["id"],
            channel=turn.conversation["channel"],
        )
    return f"Cancelled the {appt['service']} on {_label(appt['starts_at'].astimezone(turn.tz))}."


async def _reschedule_appointment(config: RunnableConfig, slot: str) -> str:
    turn = turn_of(config)
    start, _ = _resolve_slot(turn, slot)
    if not start:
        return "Could not identify the new slot. Call check_availability first and ask the customer to pick an option."
    async with db.tx([turn.tenant_id]) as c:
        appt = await _latest_booking(c, turn)
        if appt:
            await c.execute("update appointments set status = 'cancelled' where id = $1", appt["id"])
    result = await _book_appointment(config, slot, service=appt["service"] if appt else None)
    return ("Rescheduled. " if appt else "") + result


# ---------------------------------------------------------------- handover


async def _handover_to_human(config: RunnableConfig, reason: str) -> str:
    turn_of(config).handover_reason = reason or "customer needs a person"
    return "Handover started. A team member will continue this conversation."


class SearchArgs(BaseModel):
    query: str = Field(description="Search query in English, rewritten from the customer's question")


class AvailabilityArgs(BaseModel):
    date_from: str | None = Field(None, description="First day to check, YYYY-MM-DD (default: today)")
    date_to: str | None = Field(None, description="Last day to check, YYYY-MM-DD (max 7 days after date_from)")
    service: str | None = Field(None, description="Service key or name")


class BookArgs(BaseModel):
    slot: str = Field(description="The option number the customer picked (e.g. 'option 2') or an ISO datetime")
    service: str | None = Field(None, description="Service key or name")
    name: str | None = Field(None, description="Customer name if known")
    phone: str | None = Field(None, description="Phone placeholder such as <PHONE_1> if given")
    email: str | None = Field(None, description="Email placeholder such as <EMAIL_1> if given")


class SlotArgs(BaseModel):
    slot: str = Field(description="The new option number or ISO datetime")


class HandoverArgs(BaseModel):
    reason: str = Field(description="Short reason, e.g. 'customer asked for a person' or 'medical question'")


class NoArgs(BaseModel):
    pass


def make_tools(agent: dict[str, Any]) -> list[StructuredTool]:
    def t(fn, name: str, desc: str, schema: type[BaseModel]) -> StructuredTool:
        return StructuredTool.from_function(coroutine=fn, name=name, description=desc, args_schema=schema)

    label = agent["config"].get("recommendation", {}).get("label", "options")
    return [
        t(
            _search_knowledge,
            "search_knowledge",
            "Search the business's documents. Use for any factual question (prices, amenities, policies, services). Results are labelled [S1], [S2]...",
            SearchArgs,
        ),
        t(
            _update_lead,
            "update_lead",
            "Save qualification details the customer just shared. Call it whenever they reveal any of these fields.",
            _lead_model(agent["config"]["qualification"]),
        ),
        t(_recommend_items, "recommend_items", f"Recommend {label} from the catalog that match the customer's needs.", RecommendArgs),
        t(_check_availability, "check_availability", "List free appointment slots. Always call before booking.", AvailabilityArgs),
        t(_book_appointment, "book_appointment", "Book the slot the customer chose from the options you offered.", BookArgs),
        t(_reschedule_appointment, "reschedule_appointment", "Move the customer's upcoming booking to a newly chosen slot.", SlotArgs),
        t(_cancel_appointment, "cancel_appointment", "Cancel the customer's upcoming booking.", NoArgs),
        t(
            _handover_to_human,
            "handover_to_human",
            "Hand the conversation to a human team member (customer asks for a person, is upset, or the topic is sensitive/medical/legal).",
            HandoverArgs,
        ),
    ]
