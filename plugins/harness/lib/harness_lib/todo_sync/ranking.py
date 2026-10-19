"""Deterministic TODO ranking: recompute ``priority`` and the rank order from a catalog's ``ranking_method``.

``value = severity * impact_weight``, ``cost = loe_points * blast_factor``,
``score = round(value / sqrt(cost) * (1 + bonus), 4)`` where ``bonus`` is the method's ``unblock_bonus`` when
the item unblocks at least one item. Order: score descending, then severity descending, LoE points
ascending, primary source (``sources[0]``) type, issue number or ref, source item text, title.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Tuple

SOURCE_TYPE_ORDER = {"gh_issue": 0, "impl_stub": 1, "research_folder": 2}
_UNKNOWN_TYPE = len(SOURCE_TYPE_ORDER)
_TABLES = ("impact_weights", "loe_points", "blast_factors")


class RankingError(ValueError):
    """The ranking method or an item lacks a value the formula needs."""


@dataclass(frozen=True)
class RankingMethod:
    """The numeric part of a catalog's ``ranking_method``."""

    impact_weights: Mapping[str, float]
    loe_points: Mapping[str, float]
    blast_factors: Mapping[str, float]
    unblock_bonus: float


def method_from(raw: Any) -> RankingMethod:
    """A ``RankingMethod`` from the catalog's ``ranking_method`` object."""
    if not isinstance(raw, dict):
        raise RankingError("ranking_method is not an object")
    missing = [k for k in (*_TABLES, "unblock_bonus") if k not in raw]
    if missing:
        raise RankingError(f"ranking_method lacks {', '.join(missing)}")
    return RankingMethod(dict(raw["impact_weights"]), dict(raw["loe_points"]), dict(raw["blast_factors"]),
                         float(raw["unblock_bonus"]))


def _lookup(table: Mapping[str, float], key: Any, name: str) -> float:
    if key not in table:
        raise RankingError(f"{name} has no entry for {key!r}")
    return table[key]


def score(item: Dict[str, Any], method: RankingMethod) -> Tuple[float, Dict[str, float]]:
    """``(score, components)`` for one item, rounded as the catalog stores them."""
    weight = _lookup(method.impact_weights, item.get("impact"), "impact_weights")
    value = item["severity"] * weight
    points = _lookup(method.loe_points, (item.get("loe") or {}).get("size"), "loe_points")
    factor = _lookup(method.blast_factors, (item.get("blast_radius") or {}).get("level"), "blast_factors")
    cost = points * factor
    if cost <= 0:
        raise RankingError(f"loe_points x blast_factors is {cost}, the score needs a positive cost")
    base = value / math.sqrt(cost)
    bonus = method.unblock_bonus if item.get("unblocks") else 0.0
    components = {"impact_weight": weight, "value": round(value, 4), "loe_points": points,
                  "blast_factor": factor, "cost": round(cost, 4), "base_score": round(base, 4),
                  "unblock_bonus": bonus}
    return round(base * (1 + bonus), 4), components


def _issue_number(ref: Any) -> int:
    try:
        return int(str(ref).lstrip("#"))
    except ValueError:
        return 0


def sort_key(item: Dict[str, Any], method: RankingMethod, value: float) -> Tuple[Any, ...]:
    """Rank order key of ``item`` given its score ``value``."""
    sources = item.get("sources") or [{}]
    src = sources[0]
    is_gh = src.get("type") == "gh_issue"
    points = method.loe_points.get((item.get("loe") or {}).get("size"), math.inf)
    return (-value, -item.get("severity", 0), points, SOURCE_TYPE_ORDER.get(src.get("type"), _UNKNOWN_TYPE),
            _issue_number(src.get("ref")) if is_gh else 0, "" if is_gh else str(src.get("ref", "")),
            src.get("item", ""), item.get("title", ""))


def expected_order(items: List[Dict[str, Any]], method: RankingMethod) -> List[str]:
    """Item ids in the order the recomputed scores and tie breakers put them; ids are keyed as ``str``."""
    keyed = [(sort_key(i, method, score(i, method)[0]), str(i.get("id"))) for i in items]
    return [item_id for _, item_id in sorted(keyed, key=lambda pair: pair[0])]
