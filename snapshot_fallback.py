from __future__ import annotations

from copy import deepcopy
from typing import Any


MINIMUM_REPORT_CANDIDATES = 5


def has_valid_candidate_snapshot(
    snapshot: dict[str, Any],
    *,
    minimum: int = MINIMUM_REPORT_CANDIDATES,
) -> bool:
    return len(snapshot.get("tw_candidates") or []) >= minimum


def apply_candidate_fallback(
    snapshot: dict[str, Any],
    fallback_snapshot: dict[str, Any] | None,
    *,
    minimum: int = MINIMUM_REPORT_CANDIDATES,
) -> dict[str, Any]:
    """Guarantee a complete report list without creating formal fallback signals."""
    current = snapshot.get("tw_candidates") or []
    if len(current) >= minimum:
        for item in current:
            item.setdefault("eligible_for_performance", True)
            item.setdefault("candidate_freshness", "current")
        snapshot["candidate_provenance"] = {
            "mode": "current",
            "as_of": snapshot.get("market_data_date"),
            "candidate_count": len(current),
        }
        return snapshot

    fallback_snapshot = fallback_snapshot or {}
    fallback_candidates = fallback_snapshot.get("tw_candidates") or []
    if len(fallback_candidates) < minimum:
        snapshot["candidate_provenance"] = {
            "mode": "unavailable",
            "as_of": snapshot.get("market_data_date"),
            "candidate_count": len(current),
        }
        return snapshot

    fallback_date = str(
        fallback_snapshot.get("market_data_date")
        or fallback_snapshot.get("report_date")
        or fallback_snapshot.get("updated_at")
        or ""
    )[:10]
    copied_candidates = deepcopy(fallback_candidates)
    for rank, item in enumerate(copied_candidates, start=1):
        item["rank"] = rank
        item["eligible_for_performance"] = False
        item["candidate_freshness"] = "last_valid_snapshot"
        item["fallback_source_date"] = fallback_date
        item.setdefault("price_date", fallback_date or None)
        item["data_quality"] = f"沿用最近有效快照 {fallback_date}".strip()

    snapshot["tw_candidates"] = copied_candidates
    snapshot["theme_summary"] = deepcopy(fallback_snapshot.get("theme_summary") or [])
    snapshot["candidate_provenance"] = {
        "mode": "last_valid_snapshot",
        "as_of": fallback_date,
        "source_updated_at": fallback_snapshot.get("updated_at"),
        "candidate_count": len(copied_candidates),
        "current_run_candidate_count": len(current),
        "eligible_for_performance": False,
    }
    coverage = dict(snapshot.get("selection_coverage") or {})
    coverage["fallback_used"] = True
    coverage["fallback_candidate_count"] = len(copied_candidates)
    coverage["fallback_source_date"] = fallback_date
    snapshot["selection_coverage"] = coverage
    return snapshot
