from portfolio_risk import build_portfolio_risk, build_research_governance


def test_portfolio_risk_flags_concentration_turnover_and_drawdown() -> None:
    snapshot = {
        "tw_candidates": [
            {
                "code": str(1000 + index),
                "theme": "半導體",
                "industry": "半導體業",
                "avg_turnover_million": 1000,
                "candidate_channel": "primary",
            }
            for index in range(4)
        ]
    }
    previous = {
        "tw_candidates": [
            {"code": str(2000 + index), "candidate_channel": "primary"}
            for index in range(4)
        ]
    }

    risk = build_portfolio_risk(
        snapshot,
        previous_snapshot=previous,
        performance_summary={"max_drawdown_pct": -20.0},
    )

    assert risk["status"] == "breach"
    assert risk["max_theme"]["weight"] == 1.0
    assert risk["one_way_turnover"] == 1.0
    assert any("主題集中度" in message for message in risk["breaches"])
    assert any("換手率" in message for message in risk["breaches"])
    assert any("最大回撤" in message for message in risk["breaches"])


def test_research_governance_blocks_small_sample_promotion() -> None:
    governance = build_research_governance(
        {"status": "insufficient_data", "ready_for_selection": False},
        {"signal_dates": 5},
    )

    assert governance["status"] == "blocked_from_promotion"
    assert governance["strategy_version_required_for_change"] is True
    assert governance["automatic_hyperparameter_search"] is False
    assert governance["pbo_estimate"] is None
