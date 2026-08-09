import rpi_main


def test_dry_run_only_writes_research_snapshot(monkeypatch, tmp_path) -> None:
    saved: list[str] = []
    forbidden: list[str] = []
    research_path = str(tmp_path / "research.json")
    monkeypatch.setattr(rpi_main, "DRY_RUN", True)
    monkeypatch.setattr(rpi_main, "RESEARCH_SNAPSHOT_FILE", research_path)
    monkeypatch.setattr(rpi_main, "reset_data_status", lambda: None)
    monkeypatch.setattr(rpi_main, "validate_runtime_config", lambda: [])
    monkeypatch.setattr(rpi_main, "resolve_mode", lambda: "POST")
    monkeypatch.setattr(rpi_main, "fetch_all_news", lambda **kwargs: ([], []))
    monkeypatch.setattr(rpi_main, "record_news_status", lambda *args: None)
    monkeypatch.setattr(rpi_main, "get_all_market_data", lambda **kwargs: {})
    monkeypatch.setattr(
        rpi_main,
        "build_daily_snapshot",
        lambda *args, **kwargs: {
            "mode": "POST",
            "updated_at": "2026-07-16 14:00:00",
            "run_context": kwargs["run_context"],
            "tw_candidates": [],
            "small_mid_candidates": [],
        },
    )
    monkeypatch.setattr(rpi_main, "get_data_status", lambda: {})
    monkeypatch.setattr(
        rpi_main,
        "summarize_performance",
        lambda **kwargs: {"count": 0, "signal_dates": 0},
    )
    monkeypatch.setattr(rpi_main, "build_strategy_optimization", lambda: {})
    monkeypatch.setattr(
        rpi_main,
        "build_research_model_report",
        lambda **kwargs: {"status": "insufficient_data", "ready_for_selection": False},
    )
    monkeypatch.setattr(rpi_main, "build_portfolio_risk", lambda *args, **kwargs: {})
    monkeypatch.setattr(rpi_main, "build_research_governance", lambda *args: {})
    monkeypatch.setattr(rpi_main, "format_market_report", lambda snapshot: "report")
    monkeypatch.setattr(
        rpi_main,
        "save_daily_snapshot",
        lambda snapshot, path: saved.append(str(path)),
    )
    monkeypatch.setattr(
        rpi_main,
        "evaluate_signal_performance",
        lambda **kwargs: forbidden.append("performance"),
    )
    monkeypatch.setattr(
        rpi_main,
        "append_signal_history",
        lambda snapshot: forbidden.append("history"),
    )
    monkeypatch.setattr(rpi_main, "notify_report", lambda text: forbidden.append("notify"))
    monkeypatch.setattr(rpi_main, "save_summary_to_sheet", lambda snapshot: forbidden.append("sheet"))
    monkeypatch.setattr(
        rpi_main,
        "publish_dashboard_snapshot",
        lambda snapshot: forbidden.append("dashboard_publish"),
    )

    rpi_main.main()

    assert saved == [research_path]
    assert forbidden == []
