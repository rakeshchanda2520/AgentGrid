"""Provider-agnostic chat models via LangChain (seam: `chat_model`).

Every provider goes through `init_chat_model`: Anthropic natively, everything else (OpenAI, OpenRouter,
Qwen/DashScope, Ollama, vLLM, any OpenAI-compatible URL) through the OpenAI client with a base_url.
With no API key configured, agents run on `OfflineModel`: a rule-based stand-in that drives the same
tools, RAG and workflows, so the demo never breaks and tests need no network.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import asyncpg
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.config import settings
from app.security import decrypt

BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "ollama": "http://localhost:11434/v1",
}
# USD per million tokens (input, output). Providers can override per model in llm_providers.prices.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}


@dataclass
class ModelSpec:
    kind: str
    model: str
    api_key: str = ""
    base_url: str = ""
    prices: dict[str, Any] = field(default_factory=dict)
    provider_name: str = "platform"

    @property
    def offline(self) -> bool:
        return self.kind == "offline" or (not self.api_key and self.kind != "ollama")

    @property
    def label(self) -> str:
        return "offline-demo" if self.offline else f"{self.kind}:{self.model}"


def platform_spec(cheap: bool = False) -> ModelSpec:
    s = settings()
    return ModelSpec(
        kind=s.llm_provider,
        model=s.llm_cheap_model if cheap else s.llm_model,
        api_key=s.llm_api_key,
        base_url=s.llm_base_url,
        provider_name="platform",
    )


def chat_model(spec: ModelSpec, *, temperature: float = 0.2, max_tokens: int = 900) -> BaseChatModel:
    if spec.offline:
        return OfflineModel()
    s = settings()
    if spec.kind == "anthropic":
        return init_chat_model(
            spec.model,
            model_provider="anthropic",
            api_key=spec.api_key,
            timeout=s.llm_timeout_s,
            max_retries=1,
            max_tokens=max_tokens,
        )
    headers = {"HTTP-Referer": s.console_url, "X-Title": "AgentGrid"} if spec.kind == "openrouter" else None
    return init_chat_model(
        spec.model,
        model_provider="openai",
        api_key=spec.api_key or "not-needed",
        base_url=spec.base_url or BASE_URLS.get(spec.kind),
        timeout=s.llm_timeout_s,
        max_retries=1,
        temperature=temperature,
        max_tokens=max_tokens,
        stream_usage=True,
        default_headers=headers,
    )


async def specs_for_agent(c: asyncpg.Connection, agent: dict[str, Any]) -> tuple[ModelSpec, ModelSpec, ModelSpec | None]:
    """(main, cheap, fallback) model specs: the agent's own provider if set, else the platform default."""

    async def provider(pid) -> dict[str, Any] | None:
        return dict(r) if pid and (r := await c.fetchrow("select * from llm_providers where id = $1", pid)) else None

    def spec(p: dict[str, Any] | None, model: str | None, cheap: bool) -> ModelSpec:
        if not p:
            base = platform_spec(cheap)
            if model and not base.offline:
                base.model = model
            return base
        return ModelSpec(
            kind=p["kind"],
            model=model or (p["cheap_model"] if cheap else p["default_model"]) or p["default_model"],
            api_key=decrypt(p["tenant_id"], p["api_key_enc"]) or "",
            base_url=p["base_url"] or "",
            prices=p["prices"] or {},
            provider_name=p["name"],
        )

    main_p = await provider(agent.get("provider_id"))
    main = spec(main_p, agent.get("model"), False)
    cheap = spec(main_p, agent.get("cheap_model"), True)
    fb = None
    if agent.get("fallback_provider_id") or agent.get("fallback_model"):
        fb_p = await provider(agent.get("fallback_provider_id")) or main_p
        fb = spec(fb_p, agent.get("fallback_model"), False)
    return main, cheap, fb


def cost_usd(spec: ModelSpec, tokens_in: int, tokens_out: int) -> float | None:
    price = spec.prices.get(spec.model) or PRICES.get(spec.model.split("/")[-1])
    if spec.offline:
        return 0.0
    if not price:
        return None
    return round(tokens_in / 1e6 * price[0] + tokens_out / 1e6 * price[1], 6)


# --------------------------------------------------------------------------------------------------
# Offline demo model: deterministic, tool-calling, good enough to demo every flow without an API key.
# --------------------------------------------------------------------------------------------------

_QUESTIONS = {
    "name": "May I have your name?",
    "phone": "What's the best phone number to reach you?",
    "email": "What's your email address?",
    "intent": "Are you looking to buy, rent or invest?",
    "location": "Which area are you interested in?",
    "budget": "What budget range do you have in mind?",
    "property_type": "What type of property: apartment, villa or plot?",
    "timeline_months": "When are you planning to move in or buy?",
    "financing": "Will you use a home loan or pay directly?",
    "concern": "What would you like help with: a check-up, cleaning, whitening, braces or something else?",
    "preferred_date": "When would you like to come in?",
    "new_patient": "Have you visited us before?",
}
_STOP = set(
    "the and for you your are is was what how when where which who can could would does do did have has with from this that "
    "there their about any kya hai kitna price cost much want need please tell me near project projects".split()
)
_CONCERNS = ["cleaning", "whitening", "braces", "aligners", "implant", "root canal", "check-up", "checkup", "toothache", "pain", "filling", "crown"]


def _money(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(crores?|cr|lakhs?|lacs?|l\b|k\b)", text, re.I)
    if m:
        n, unit = float(m.group(1)), m.group(2).lower()
        return n * (1e7 if unit.startswith("c") else 1e5 if unit.startswith("l") else 1e3)
    m = re.search(r"(?:₹|rs\.?|inr)\s*([\d,]{4,})", text, re.I)
    return float(m.group(1).replace(",", "")) if m else None


def _extract(text: str) -> dict[str, Any]:
    t = text.lower()
    out: dict[str, Any] = {}
    if (b := _money(text)) is not None:
        out["budget"] = b
    if m := re.search(r"\b(?i:i am|i'm|im|my name is|this is|name's)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", text):
        out["name"] = m.group(1)
    if m := re.search(r"<PHONE_\d+>", text):
        out["phone"] = m.group()
    if m := re.search(r"<EMAIL_\d+>", text):
        out["email"] = m.group()
    if m := re.search(r"(\d+)\s*(months?|weeks?|years?)", t):
        n = int(m.group(1))
        out["timeline_months"] = n if m.group(2).startswith("month") else max(1, n // 4) if m.group(2).startswith("week") else n * 12
    for word, val in (("invest", "invest"), ("rent", "rent"), ("buy", "buy"), ("purchase", "buy")):
        if re.search(rf"\b{word}", t):
            out["intent"] = val
            break
    if "pre-approved" in t or "preapproved" in t or "pre approved" in t:
        out["financing"] = "loan_preapproved"
    elif "loan" in t:
        out["financing"] = "loan"
    elif "cash" in t or "self-funded" in t:
        out["financing"] = "cash"
    for word, val in (
        ("villa", "villa"),
        ("plot", "plot"),
        ("commercial", "commercial"),
        ("bhk", "apartment"),
        ("apartment", "apartment"),
        ("flat", "apartment"),
    ):
        if word in t:
            out["property_type"] = val
            break
    if m := re.search(r"\b(\d)\s*bhk", t):
        out["bedrooms"] = int(m.group(1))
    if m := re.search(r"\b(?:in|at|near|around)\s+([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?)", text):
        if m.group(1).lower() not in {"the", "next", "a", "my"}:
            out["location"] = m.group(1)
    for c in _CONCERNS:
        if c in t:
            out["concern"] = "check-up" if c == "checkup" else c
            break
    if "first time" in t or "new patient" in t or "never visited" in t:
        out["new_patient"] = True
    return out


def _tool_text(messages: list[BaseMessage]) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for m in reversed(messages):
        if isinstance(m, ToolMessage):
            results.append((m.name or "", str(m.content)))
        else:
            break
    return list(reversed(results))


class OfflineModel(BaseChatModel):
    tool_names: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "agentgrid-offline"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model_name": "offline-demo"}

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self.model_copy(update={"tool_names": [convert_to_openai_tool(t)["function"]["name"] for t in tools]})

    def with_structured_output(self, schema, **kwargs):  # type: ignore[override]
        raise NotImplementedError("offline model has no structured output; callers use heuristics")

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        msg = AIMessage(content="", response_metadata={"model_name": "offline-demo"})
        last = messages[-1] if messages else None
        system = next((str(m.content) for m in messages if isinstance(m, SystemMessage)), "")
        if isinstance(last, ToolMessage):
            msg.content = self._answer(messages, system)
        elif isinstance(last, HumanMessage):
            calls = self._plan(str(last.content))
            if calls:
                msg.tool_calls = [{"name": n, "args": a, "id": f"call_{i}_{n}", "type": "tool_call"} for i, (n, a) in enumerate(calls)]
            else:
                name = re.search(r"You are (\w+)", system)
                msg.content = f"Hi! I'm {name.group(1) if name else 'your assistant'}. How can I help you today?"
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _plan(self, text: str) -> list[tuple[str, dict[str, Any]]]:
        t = text.lower().strip()
        calls: list[tuple[str, dict[str, Any]]] = []
        has = set(self.tool_names)
        if re.fullmatch(r"(hi|hello|hey|hii|namaste|good (morning|evening|afternoon))[!. ]*", t):
            return []
        fields = _extract(text)
        if fields and "update_lead" in has:
            calls.append(("update_lead", fields))
        ordinal = re.search(r"\b(first|second|third|fourth|fifth|sixth)\b.*\b(slot|option|one)\b", t)
        slot = re.search(r"\b(?:option|slot|#)\s*(\d)\b|^\s*(\d)\s*$", t)
        if (slot or ordinal) and "book_appointment" in has:
            n = slot.group(1) or slot.group(2) if slot else str(["first", "second", "third", "fourth", "fifth", "sixth"].index(ordinal.group(1)) + 1)
            calls.append(("book_appointment", {"slot": f"option {n}"}))
        elif re.search(r"\b(book|appointment|schedule|site visit|visit|slot|available|availability)\b", t) and "check_availability" in has:
            start = date.today() + timedelta(days=1)
            calls.append(("check_availability", {"date_from": start.isoformat(), "date_to": (start + timedelta(days=3)).isoformat()}))
        wants_reco = re.search(r"\b(recommend|suggest|options|show me|looking for|which (treatment|package|project)|best for)\b", t)
        if wants_reco and not (slot or ordinal) and "recommend_items" in has:
            prefs = {k: v for k, v in fields.items() if k in {"location", "budget", "property_type", "bedrooms", "concern"}}
            calls.append(("recommend_items", prefs | {"keywords": text[:120]}))
        is_question = "?" in t or re.match(r"(what|how|where|when|why|which|do|does|is|are|can|tell|price|cost)\b", t)
        if "search_knowledge" in has and (is_question or not calls):
            calls.append(("search_knowledge", {"query": text[:300]}))
        return calls

    @staticmethod
    def _best_chunk(content: str, question: str) -> str | None:
        """Pick the retrieved chunk sharing the most content words with the question; None if nothing overlaps."""
        words = {w for w in re.findall(r"[a-z0-9]{3,}", question.lower()) if w not in _STOP}
        best, best_hits = None, 0
        for m in re.finditer(r"\[(S\d+)\] \(([^)]*)\)\s*(.+?)(?=\n\[S\d+\]|\Z)", content, re.S):
            body = m.group(3).lower()
            hits = sum(1 for w in words if w in body or (w.endswith("s") and w[:-1] in body))
            if hits > best_hits:
                best, best_hits = m, hits
        if not best:
            return None
        # Read the chunk as (heading, body) sections; a matching heading (FAQ question) counts double.
        sections: list[tuple[str, list[str]]] = [("", [])]
        for ln in best.group(3).splitlines():
            ln = ln.strip()
            if ln.startswith("#"):
                sections.append((ln.strip("# "), []))
            elif ln:
                sections[-1][1].append(ln.lstrip("- ").strip())

        def overlap(s: str) -> int:
            return sum(1 for w in words if w in s.lower())

        head, body = max(sections, key=lambda s: 2 * overlap(s[0]) + max((overlap(b) for b in s[1]), default=0))
        if not body:
            return None
        lines = body if overlap(head) else sorted(body, key=lambda b: -overlap(b))
        return f"{' '.join(lines[:2])} [{best.group(1)}]"

    def _answer(self, messages: list[BaseMessage], system: str) -> str:
        question = next((str(m.content) for m in reversed(messages) if isinstance(m, HumanMessage)), "")
        parts: list[str] = []
        follow_up = ""
        for name, content in _tool_text(messages):
            if name == "search_knowledge":
                best = None if content.startswith("NO_RELEVANT_RESULTS") else self._best_chunk(content, question)
                parts.append(best or "I'm not certain about that and I don't want to guess. Would you like me to connect you with our team?")
            elif name in ("recommend_items", "check_availability", "book_appointment", "reschedule_appointment", "cancel_appointment"):
                parts.append(content)
            elif name == "update_lead" and (m := re.search(r"missing=([\w,]*)", content)):
                missing = [f for f in m.group(1).split(",") if f in _QUESTIONS]
                if missing:
                    follow_up = _QUESTIONS[missing[0]]
                elif "stage=qualified" in content or "stage=hot" in content:
                    follow_up = "Thanks, I have everything I need. Shall I book a visit for you?"
        if parts and "?" in question:
            follow_up = ""  # they asked something: answer it, don't interrogate
        if not parts and not follow_up:
            parts.append("Thanks, noted!")
        return "\n\n".join(p for p in [*parts, follow_up] if p)
