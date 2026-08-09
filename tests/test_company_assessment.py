import company_assessment


def test_company_quality_uses_available_revenue_without_filling_missing_values() -> None:
    strong = company_assessment.score_company_quality(
        {
            "yoy_pct": 25.0,
            "cumulative_yoy_pct": 20.0,
            "mom_pct": 5.0,
        }
    )
    missing = company_assessment.score_company_quality({})

    assert strong["score"] >= 80
    assert strong["confidence"] == "中"
    assert missing["score"] is None
    assert missing["confidence"] == "不足"


def test_event_risk_requires_company_match_and_explains_negative_keyword() -> None:
    result = company_assessment.assess_event_risk(
        [
            {"title": "其他公司下修展望", "summary": ""},
            {"title": "2330 台積電遭裁罰", "summary": "等待公司說明"},
        ],
        code="2330",
        name="台積電",
    )

    assert result["level"] == "中"
    assert result["related_news_count"] == 1
    assert "裁罰" in result["summary"]


def test_high_quality_cheap_but_weak_timing_becomes_quality_pullback(monkeypatch) -> None:
    monkeypatch.setattr(
        company_assessment,
        "get_valuation_snapshot",
        lambda code, market: {
            "score": 74.0,
            "pe_ratio": 15.0,
            "pb_ratio": 2.0,
            "dividend_yield_pct": 3.0,
            "comparison_basis": "同業",
        },
    )

    result = company_assessment.build_company_assessment(
        code="2330",
        name="台積電",
        market="上市",
        revenue={
            "yoy_pct": 25.0,
            "cumulative_yoy_pct": 20.0,
            "mom_pct": 5.0,
        },
        metrics={"ma20": 100.0},
        entry={"entry_score": 38.0, "entry_plan": {}},
        news_items=[{"title": "台積電營運更新", "summary": ""}],
    )

    assert result["company_quality_score"] >= 80
    assert result["valuation_attractiveness_score"] == 74.0
    assert result["entry_timing_score"] == 38.0
    assert result["opportunity_label"] == "優質回檔觀察"
    assert "站回 MA20 約 100.00" in result["plain_language_advice"]

