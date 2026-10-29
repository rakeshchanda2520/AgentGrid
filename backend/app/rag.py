"""Knowledge base: load → split (LangChain) → embed → store; hybrid retrieval (pgvector + full-text, RRF).

Embeddings: local FastEmbed (bge-small, 384-d, no data leaves the server) or any OpenAI-compatible
embedding API (asked for 384 dimensions). If neither is available, search silently degrades to
Postgres full-text only, so the agent keeps working.
"""

import asyncio
import io
import logging
import re
from typing import Any
from uuid import UUID

import httpx
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app import db, jobs
from app.config import settings

log = logging.getLogger("agentgrid.rag")
_model = None
_splitter = RecursiveCharacterTextSplitter(chunk_size=650, chunk_overlap=100, separators=["\n## ", "\n# ", "\n\n", "\n", ". ", " "])
PAGE_BREAK = "\f"


def _fastembed():
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        _model = TextEmbedding("BAAI/bge-small-en-v1.5", cache_dir=settings().fastembed_cache)
    return _model


async def embed(texts: list[str], *, query: bool = False) -> list[list[float]] | None:
    s = settings()
    try:
        if s.embeddings == "fastembed":
            model = _fastembed()
            fn = model.query_embed if query else model.embed
            return await asyncio.to_thread(lambda: [v.tolist() for v in fn(texts)])
        if s.embeddings == "openai":
            from langchain_openai import OpenAIEmbeddings

            e = OpenAIEmbeddings(
                model=s.embeddings_model, dimensions=384, api_key=s.embeddings_api_key or s.llm_api_key, base_url=s.embeddings_base_url or None
            )
            return [await e.aembed_query(texts[0])] if query and len(texts) == 1 else await e.aembed_documents(texts)
    except Exception as exc:  # degrade to full-text search rather than fail the conversation
        log.warning("embeddings unavailable (%s); using full-text search only", exc)
    return None


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        return PAGE_BREAK.join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    if name.endswith(".docx"):
        from docx import Document

        return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    text = data.decode("utf-8", errors="ignore")
    return html_to_text(text) if name.endswith((".html", ".htm")) else text


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", "\n", html)
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


async def fetch_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        raise ValueError("URL must start with http(s)://")
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "AgentGridBot/1.0"}) as client:
        r = await client.get(url)
        r.raise_for_status()
        return html_to_text(r.text)[:200_000]


@jobs.handler("kb.ingest")
async def ingest(payload: dict[str, Any], tenant_id: UUID | None) -> None:
    sid = payload["source_id"]
    async with db.tx([tenant_id]) as c:
        src = db.row(await c.fetchrow("select * from knowledge_sources where id = $1", UUID(sid)))
    if not src:
        return
    try:
        text = src["raw_text"] or (await fetch_url(src["uri"]) if src["type"] == "url" else "")
        pieces: list[tuple[int | None, str]] = []
        pages = text.split(PAGE_BREAK)
        for pno, page in enumerate(pages, start=1):
            for chunk in _splitter.split_text(page):
                if chunk.strip():
                    pieces.append((pno if len(pages) > 1 else None, f"{src['title']}\n{chunk.strip()}"))
        vectors = await embed([p[1] for p in pieces]) if pieces else []
        async with db.tx([tenant_id]) as c:
            await c.execute("delete from knowledge_chunks where source_id = $1", src["id"])
            await c.executemany(
                """insert into knowledge_chunks (tenant_id, agent_id, source_id, idx, content, page, embedding)
                   values ($1, $2, $3, $4, $5, $6, $7::vector)""",
                [
                    (tenant_id, src["agent_id"], src["id"], i, content, page, db.vec(vectors[i]) if vectors else None)
                    for i, (page, content) in enumerate(pieces)
                ],
            )
            await c.execute(
                "update knowledge_sources set status = 'ready', error = null, chunk_count = $2, raw_text = $3 where id = $1",
                src["id"],
                len(pieces),
                text,
            )
    except Exception as exc:
        async with db.tx([tenant_id]) as c:
            await c.execute("update knowledge_sources set status = 'error', error = $2 where id = $1", src["id"], str(exc)[:500])
        raise


SEARCH_SQL = """
with qv as (select $3::vector as v),
q as (select to_tsquery('english', coalesce(nullif(array_to_string(tsvector_to_array(to_tsvector('english', $2)), ' | '), ''), 'zzqqxx')) as q),
v as (
  select c.id, 1 - (c.embedding <=> qv.v) as sim, row_number() over (order by c.embedding <=> qv.v) as r
  from knowledge_chunks c, qv where c.agent_id = $1 and c.embedding is not null and qv.v is not null
  order by c.embedding <=> qv.v limit 20
),
f as (
  select c.id, ts_rank(c.tsv, q.q) as rank, row_number() over (order by ts_rank(c.tsv, q.q) desc) as r
  from knowledge_chunks c, q where c.agent_id = $1 and c.tsv @@ q.q order by rank desc limit 20
)
select c.id, c.content, c.page, s.title, v.sim, f.rank,
       coalesce(1.0 / (60 + v.r), 0) + coalesce(1.0 / (60 + f.r), 0) as rrf
from knowledge_chunks c
join knowledge_sources s on s.id = c.source_id
left join v on v.id = c.id
left join f on f.id = c.id
where v.id is not null or f.id is not null
order by rrf desc limit $4
"""


async def search(tenant_id: UUID, agent_id: UUID, query: str, k: int = 5) -> tuple[list[dict[str, Any]], bool]:
    """Top-k chunks and whether retrieval is confident enough to answer from."""
    qv = await embed([query], query=True)
    async with db.tx([tenant_id]) as c:
        hits = db.rows(await c.fetch(SEARCH_SQL, agent_id, query, db.vec(qv[0]) if qv else None, k))
    if not hits:
        return [], False
    best_sim = max((h["sim"] or 0) for h in hits)
    best_rank = max((h["rank"] or 0) for h in hits)
    # Calibrated with tools/probe_rag.py (bge-small): on-topic ≈ 0.60-0.87, off-topic ≈ 0.50-0.59. A keyword match lowers
    # the bar a little. Borderline hits still reach the LLM, which is told to answer only from the retrieved text.
    min_sim = settings().retrieval_min_similarity
    confident = (best_sim >= min_sim or (best_sim >= min_sim - 0.07 and best_rank >= 0.03)) if qv else best_rank >= 0.05
    return hits, confident
