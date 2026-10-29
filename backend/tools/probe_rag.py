"""Calibrate retrieval: `uv run python -u -m tools.probe_rag` prints confidence and scores for known good / off-topic questions."""

import asyncio

from app import db, rag

QUERIES = {
    "pk_skyline_aria": [
        "price of 3 BHK in Whitefield",
        "is there a metro near Orchid Heights",
        "Lakeview possession date",
        "cancellation refund policy",
        "home loan banks",
        "Orchid Heights 3BHK kitna price hai",
        "does the project have a helipad",
        "what is the capital of France",
    ],
    "pk_brightsmile_mia": [
        "teeth whitening cost",
        "are you open on sunday",
        "do you accept insurance",
        "root canal molar price",
        "price of a lamborghini",
        "do you do hair transplant",
    ],
}


async def main() -> None:
    async with db.tx(system=True) as c:
        print(
            "chunks:",
            await c.fetchval("select count(*) from knowledge_chunks"),
            "embedded:",
            await c.fetchval("select count(*) from knowledge_chunks where embedding is not null"),
        )
        agents = {r["public_key"]: (r["id"], r["tenant_id"]) for r in await c.fetch("select id, tenant_id, public_key from agents")}
    for key, qs in QUERIES.items():
        aid, tid = agents[key]
        for q in qs:
            hits, conf = await rag.search(tid, aid, q)
            top = hits[0] if hits else {}
            body = top.get("content", "").split("\n", 1)[-1][:60]
            print(f"{conf!s:5} sim={top.get('sim') or 0:.3f} rank={top.get('rank') or 0:.3f} | {q} -> {body!r}")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
