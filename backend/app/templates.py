"""Industry agent templates (YAML in app/templates). An agent's config starts as a copy of its template."""

import copy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DIR = Path(__file__).parent / "templates"
CONFIG_KEYS = ("greeting", "quick_replies", "qualification", "recommendation", "booking", "handover")


@lru_cache
def all_templates() -> dict[str, dict[str, Any]]:
    return {f.stem: yaml.safe_load(f.read_text(encoding="utf-8")) for f in sorted(DIR.glob("*.yaml"))}


def get(key: str) -> dict[str, Any]:
    t = all_templates().get(key)
    if t is None:
        raise KeyError(f"unknown template {key}")
    return copy.deepcopy(t)


def agent_config(key: str) -> dict[str, Any]:
    t = get(key)
    return {k: t.get(k) for k in CONFIG_KEYS} | {"business_profile": ""}


def summary() -> list[dict[str, Any]]:
    return [
        {k: t.get(k) for k in ("key", "name", "industry", "description")}
        | {"fields": list(t["qualification"]["fields"]), "workflows": [w["name"] for w in t.get("workflows", [])]}
        for t in all_templates().values()
    ]
