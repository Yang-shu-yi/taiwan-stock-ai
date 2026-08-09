from snapshot_fallback import apply_candidate_fallback, has_valid_candidate_snapshot


def _candidates(count: int) -> list[dict]:
    return [
        {
            "code": str(2000 + index),
            "name": f"測試股{index}",
            "rank": index,
            "score": 80 - index,
        }
        for index in range(1, count + 1)
    ]


def test_current_complete_list_remains_formal() -> None:
    snapshot = {
        "market_data_date": "2026-07-22",
        "tw_candidates": _candidates(5),
    }

    result = apply_candidate_fallback(snapshot, {})

    assert result["candidate_provenance"]["mode"] == "current"
    assert all(item["eligible_for_performance"] for item in result["tw_candidates"])


def test_incomplete_list_uses_last_valid_top_five_as_display_only() -> None:
    snapshot = {
        "updated_at": "2026-07-22 08:35:00",
        "market_data_date": "2026-07-21",
        "tw_candidates": [],
        "theme_summary": [],
    }
    fallback = {
        "updated_at": "2026-07-21 13:45:00",
        "market_data_date": "2026-07-21",
        "tw_candidates": _candidates(8),
        "theme_summary": [{"theme": "金融", "leaders": ["2884 玉山金"]}],
    }

    result = apply_candidate_fallback(snapshot, fallback)

    assert has_valid_candidate_snapshot(result)
    assert result["candidate_provenance"]["mode"] == "last_valid_snapshot"
    assert result["candidate_provenance"]["as_of"] == "2026-07-21"
    assert len(result["tw_candidates"]) == 8
    assert all(item["eligible_for_performance"] is False for item in result["tw_candidates"])
    assert result["theme_summary"][0]["theme"] == "金融"
