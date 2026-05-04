import stock_analyzer


def test_revenue_snapshot_parses_twse_fields(monkeypatch) -> None:
    row = {
        "公司代號": "2330",
        "資料年月": "202604",
        "產業別": "半導體",
        "營業收入-當月營收": "259,000,000",
        "營業收入-上月比較增減(%)": "5.5",
        "營業收入-去年同月增減(%)": "30.2",
        "累計營業收入-前期比較增減(%)": "25.0",
    }
    monkeypatch.setattr(stock_analyzer, "_load_revenue_map", lambda market: {"2330": row})
    revenue = stock_analyzer.get_revenue_snapshot("2330", "上市")
    assert revenue["period"] == "202604"
    assert revenue["industry"] == "半導體"
    assert revenue["month_revenue_billion"] == 2590.0
    assert revenue["yoy_pct"] == 30.2
