"""Deterministic guardrails around the LLM: handover rules, citation validation, output filtering."""

import re
from datetime import datetime, time
from typing import Any

from langchain_core.messages import BaseMessage

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
CITE = re.compile(r"\[(S\d+)\]")


def text_of(msg: BaseMessage) -> str:
    c = msg.content
    if isinstance(c, str):
        return c
    return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in c)


def handover_rule(text: str, handover: dict[str, Any]) -> str | None:
    t = text.lower()
    for kw in handover.get("keywords", []):
        if re.search(rf"\b(talk|speak|connect|chat)\b.*\b{re.escape(kw)}\b|\b{re.escape(kw)}\b.*\b(please|now|pls)\b|^\s*{re.escape(kw)}\s*[.!?]*\s*$", t):
            return "customer asked for a person"
    for topic in handover.get("sensitive_topics", []):
        if re.search(rf"\b{re.escape(topic.lower())}\b", t):
            return f"sensitive topic: {topic}"
    return None


def check_citations(text: str, retrieved: dict[str, dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Strip [S#] markers that were never retrieved this turn; return the valid ones as citations."""
    used: list[dict[str, Any]] = []

    def keep(m: re.Match[str]) -> str:
        label = m.group(1)
        if label in retrieved:
            if label not in [u["label"] for u in used]:
                used.append({"label": label} | retrieved[label])
            return m.group(0)
        return ""

    cleaned = CITE.sub(keep, text)
    return re.sub(r"[ \t]+([.,!?])", r"\1", cleaned).strip(), used


def output_filter(text: str, blocked: list[str], max_len: int = 3500) -> str:
    for word in blocked:
        text = re.sub(rf"(?i)\b{re.escape(word)}\b", "***", text)
    text = re.sub(r"(?i)</?(thinking|system|tool_call)[^>]*>", "", text)
    return text[:max_len].strip()


def is_open(hours: dict[str, str], now: datetime) -> bool:
    span = hours.get(DAYS[now.weekday()]) or ""
    if "-" not in span:
        return False
    o, c = (time.fromisoformat(x.strip()) for x in span.split("-"))
    return o <= now.time() <= c


def handover_message(reason: str, open_now: bool, hours: dict[str, str]) -> str:
    if reason.startswith("sensitive topic"):
        lead = "That's something our team should handle personally, so I won't guess."
    elif reason == "low confidence":
        lead = "I want to make sure you get the right answer."
    else:
        lead = "Sure."
    if open_now:
        return f"{lead} I'm connecting you with a member of our team now. They'll reply right here shortly."
    today = ", ".join(f"{d.title()} {h}" for d, h in hours.items() if h)
    return f"{lead} Our team is offline right now ({today}). I've passed your conversation on and they'll reply here as soon as they're back."
