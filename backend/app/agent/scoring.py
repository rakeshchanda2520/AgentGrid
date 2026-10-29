"""Deterministic lead scoring: the LLM only supplies field values; points and stage come from the template."""

from typing import Any

STAGE_ORDER = ["new", "engaged", "qualified", "hot", "booked"]


def _points(value: Any, spec: dict[str, Any]) -> float:
    weight = float(spec.get("weight", 0))
    rule = spec.get("score")
    if not rule:
        return weight
    for part in str(rule).split(","):
        cond, _, pts = part.strip().rpartition(":")
        try:
            if cond == "else":
                return float(pts)
            for op in ("<=", ">=", "<", ">"):
                if cond.startswith(op):
                    n, lim = float(value), float(cond[len(op) :])
                    if (op == "<=" and n <= lim) or (op == ">=" and n >= lim) or (op == "<" and n < lim) or (op == ">" and n > lim):
                        return float(pts)
                    break
            else:
                if str(value) == cond:
                    return float(pts)
        except (TypeError, ValueError):
            continue
    return 0.0


def present(value: Any) -> bool:
    return value is not None and value != "" and value != []


def score(fields: dict[str, Any], qualification: dict[str, Any]) -> tuple[int, str, list[str]]:
    """Returns (score 0-100, stage, missing field names in template order)."""
    specs: dict[str, dict[str, Any]] = qualification.get("fields", {})
    total = sum(float(s.get("weight", 0)) for s in specs.values()) or 1.0
    got = sum(_points(fields[k], s) for k, s in specs.items() if present(fields.get(k)))
    pts = round(100 * got / total)
    stage = "new"
    for name in ("engaged", "qualified", "hot"):
        if pts >= qualification.get("stages", {}).get(name, 101):
            stage = name
    missing = [k for k in specs if not present(fields.get(k))]
    return pts, stage, missing


def later_stage(a: str, b: str) -> str:
    return a if STAGE_ORDER.index(a) >= STAGE_ORDER.index(b) else b
