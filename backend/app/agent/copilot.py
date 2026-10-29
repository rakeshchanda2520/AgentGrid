"""Agent Copilot for human agents: handover summary and suggested replies (cheap model, structured output).
Falls back to deterministic heuristics when the model is offline or fails."""

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.llm import ModelSpec, chat_model

log = logging.getLogger("agentgrid.copilot")


class HandoverSummary(BaseModel):
    bullets: list[str] = Field(description="Exactly 3 short bullets: what the customer wants, what is done, what is pending")
    intent: str = Field(description="Customer intent in 2-5 words")
    sentiment: str = Field(description="positive | neutral | negative")
    suggested_reply: str = Field(description="A warm first reply the human agent could send")


class Suggestions(BaseModel):
    replies: list[str] = Field(description="3 short alternative replies the human agent could send next")


def _transcript(messages: list[dict[str, Any]], limit: int = 30) -> str:
    return "\n".join(f"{m['role']}: {m['content']}" for m in messages[-limit:])


def _heuristic(messages: list[dict[str, Any]], lead: dict[str, Any] | None, reason: str) -> dict[str, Any]:
    users = [m["content"] for m in messages if m["role"] == "user"]
    fields = (lead or {}).get("fields", {})
    known = ", ".join(f"{k}: {v}" for k, v in fields.items() if v) or "no details captured yet"
    neg = any(w in " ".join(users).lower() for w in ("angry", "bad", "worst", "useless", "frustrat", "not happy", "complain"))
    return {
        "bullets": [
            f"Customer first asked: {users[0][:120]}" if users else "Customer opened the chat",
            f"Captured: {known}",
            f"Escalated because: {reason}",
        ],
        "intent": "needs a person" if "person" in reason else reason[:40],
        "sentiment": "negative" if neg else "neutral",
        "suggested_reply": "Hi, I'm from the team and I've read your conversation. How can I help?",
    }


async def summarize(spec: ModelSpec, messages: list[dict[str, Any]], lead: dict[str, Any] | None, reason: str) -> dict[str, Any]:
    if spec.offline:
        return _heuristic(messages, lead, reason)
    try:
        model = chat_model(spec, temperature=0, max_tokens=500).with_structured_output(HandoverSummary, method="function_calling")
        out = await model.ainvoke(
            "Summarise this customer conversation for the human agent taking over. "
            f"Escalation reason: {reason}. Lead details: {(lead or {}).get('fields', {})}\n\n{_transcript(messages)}"
        )
        return out.model_dump()
    except Exception as exc:
        log.warning("copilot summary failed: %s", exc)
        return _heuristic(messages, lead, reason)


async def suggest(spec: ModelSpec, messages: list[dict[str, Any]]) -> list[str]:
    fallback = ["Thanks for waiting! Let me check that for you.", "Could you share a little more detail?", "I've noted that. Anything else I can help with?"]
    if spec.offline:
        return fallback
    try:
        model = chat_model(spec, temperature=0.4, max_tokens=400).with_structured_output(Suggestions, method="function_calling")
        out = await model.ainvoke("You assist a human support agent. Suggest 3 short, specific next replies to the customer.\n\n" + _transcript(messages, 20))
        return out.replies[:3] or fallback
    except Exception as exc:
        log.warning("copilot suggestions failed: %s", exc)
        return fallback
