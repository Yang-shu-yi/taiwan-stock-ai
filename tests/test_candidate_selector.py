import candidate_selector
from strategy_contract import EARLY_WATCH_CHANNEL, PRIMARY_CHANNEL, SHADOW_CHANNEL


def test_market_change_uses_percentage_not_absolute_price_change() -> None:
    low_price = candidate_selector._market_change_pct(
        {"ClosingPrice": "101", "Change": "1", "Sign": "+"}
    )
    high_price = candidate_selector._market_change_pct(
        {"ClosingPrice": "1010", "Change": "10", "Sign": "+"}
    )

    assert round(low_price, 6) == round(high_price, 6) == 1.0


def test_theme_score_is_not_biased_by_constituent_count() -> None:
    candidates = [
        {"code": "A", "name": "A", "theme": "主題A", "score": 80, "pct_5d": 0},
    ]
    candidates.extend(
        {
            "code": f"B{index}",
            "name": f"B{index}",
            "theme": "主題B",
            "score": 70,
            "pct_5d": 0,
        }
        for index in range(8)
    )

    summary = candidate_selector._theme_summary(candidates, [])

    assert summary[0]["theme"] == "主題A"
    assert summary[0]["breadth"] == 1
    assert next(item for item in summary if item["theme"] == "主題B")["breadth"] == 8


def test_daily_snapshot_keeps_core_and_radar_in_separate_channels(monkeypatch) -> None:
    monkeypatch.setattr(candidate_selector, "_recent_history", lambda symbol: None)
    monkeypatch.setattr(candidate_selector, "build_scan_universe", lambda news, quotes=None: ["2330"])
    monkeypatch.setattr(
        candidate_selector,
        "_score_tw_candidate",
        lambda code, news, benchmark=None, latest_quote=None: {
            "code": code,
            "name": "台積電",
            "score": 80,
            "pct_1d": 1.0,
            "theme": "半導體",
            "source": "core",
            "candidate_channel": PRIMARY_CHANNEL,
        },
    )
    monkeypatch.setattr(
        candidate_selector,
        "build_small_mid_cap_radar",
        lambda news, exclude_codes=None, latest_quotes=None: [
            {
                "code": "6274",
                "name": "台燿",
                "score": 90,
                "small_mid_score": 90,
                "theme": "PCB/ABF",
            }
        ],
    )
    monkeypatch.setattr(candidate_selector, "get_us_context_symbols", lambda: [])

    snapshot = candidate_selector.build_daily_snapshot(
        "PRE",
        {},
        [],
        [],
        run_context={
            "execution_environment": "research",
            "run_type": "dry_run",
            "strategy_version": "test",
            "feature_version": "test",
        },
    )

    assert [item["code"] for item in snapshot["tw_candidates"]] == ["2330"]
    assert snapshot["tw_candidates"][0]["candidate_channel"] == PRIMARY_CHANNEL
    assert [item["code"] for item in snapshot["small_mid_candidates"]] == ["6274"]
    assert snapshot["small_mid_candidates"][0]["candidate_channel"] == SHADOW_CHANNEL


def test_daily_snapshot_excludes_candidates_from_the_wrong_trading_date(monkeypatch) -> None:
    monkeypatch.setattr(candidate_selector, "_recent_history", lambda symbol: None)
    monkeypatch.setattr(candidate_selector, "load_official_daily_quotes", lambda date: {})
    monkeypatch.setattr(candidate_selector, "build_scan_universe", lambda news, quotes=None: ["2330", "2317"])
    monkeypatch.setattr(
        candidate_selector,
        "_score_tw_candidate",
        lambda code, news, benchmark=None, latest_quote=None: {
            "code": code,
            "name": code,
            "score": 80,
            "pct_1d": 1.0,
            "theme": "電子",
            "price_date": "2026-07-22" if code == "2330" else "2026-07-21",
            "candidate_channel": PRIMARY_CHANNEL,
        },
    )
    monkeypatch.setattr(candidate_selector, "build_small_mid_cap_radar", lambda *args, **kwargs: [])
    monkeypatch.setattr(candidate_selector, "get_us_context_symbols", lambda: [])

    snapshot = candidate_selector.build_daily_snapshot(
        "POST",
        {"tw_index": {"trading_date": "2026-07-22"}},
        [],
        [],
    )

    assert [item["code"] for item in snapshot["tw_candidates"]] == ["2330"]
    assert snapshot["selection_coverage"]["stale_price_excluded_count"] == 1


def test_daily_snapshot_separates_actionable_and_early_watch_lists(monkeypatch) -> None:
    monkeypatch.setattr(candidate_selector, "_recent_history", lambda symbol: None)
    monkeypatch.setattr(candidate_selector, "build_scan_universe", lambda news, quotes=None: ["2330", "1301"])

    def score(code, news, benchmark=None, latest_quote=None):
        if code == "2330":
            return {
                "code": code,
                "name": "台積電",
                "score": 82,
                "entry_score": 76,
                "entry_status": "scale_in",
                "early_watch_qualified": False,
                "early_watch_score": 20,
                "pct_1d": 1.0,
                "theme": "半導體",
                "candidate_channel": PRIMARY_CHANNEL,
            }
        return {
            "code": code,
            "name": "台塑",
            "score": 56,
            "entry_score": 54,
            "entry_status": "early_watch",
            "early_watch_qualified": True,
            "early_watch_score": 78,
            "pct_1d": 0.5,
            "theme": "塑化",
            "candidate_channel": PRIMARY_CHANNEL,
        }

    monkeypatch.setattr(candidate_selector, "_score_tw_candidate", score)
    monkeypatch.setattr(candidate_selector, "build_small_mid_cap_radar", lambda *args, **kwargs: [])
    monkeypatch.setattr(candidate_selector, "get_us_context_symbols", lambda: [])

    snapshot = candidate_selector.build_daily_snapshot("POST", {}, [], [])

    assert [item["code"] for item in snapshot["actionable_candidates"]] == ["2330"]
    assert snapshot["actionable_candidates"][0]["candidate_channel"] == PRIMARY_CHANNEL
    assert [item["code"] for item in snapshot["early_watch_candidates"]] == ["1301"]
    assert snapshot["early_watch_candidates"][0]["candidate_channel"] == EARLY_WATCH_CHANNEL


def test_intraday_focus_prioritizes_actionable_and_early_without_overextended(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        candidate_selector,
        "load_daily_snapshot",
        lambda path: {
            "actionable_candidates": [{"code": "2330"}],
            "early_watch_candidates": [{"code": "1301"}, {"code": "2330"}],
            "tw_candidates": [
                {"code": "2408", "entry_status": "overextended"},
                {"code": "2317", "entry_status": "wait_pullback"},
            ],
        },
    )

    assert candidate_selector.get_intraday_focus_codes(5, "unused.json") == [
        "2330",
        "1301",
        "2317",
    ]
