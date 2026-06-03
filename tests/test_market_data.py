import market_data


def test_institutional_fallback_uses_bfi82u(monkeypatch) -> None:
    def fail_primary(*args, **kwargs):
        raise ValueError("primary failed")

    def fake_fetch_json(*args, **kwargs):
        return {
            "data": [
                ["外資及陸資", "1", "2", "3", "100,000,000"],
                ["投信", "1", "2", "3", "50,000,000"],
                ["自營商", "1", "2", "3", "-20,000,000"],
                ["合計", "1", "2", "3", "130,000,000"],
            ]
        }

    statuses = []
    monkeypatch.setattr(market_data, "twse_json", fail_primary)
    monkeypatch.setattr(market_data, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(market_data, "record_status", lambda *args, **kwargs: statuses.append((args, kwargs)))

    result = market_data.get_institutional_trades()

    assert result["foreign"] == "+1.0億"
    assert result["trust"] == "+0.5億"
    assert result["dealer"] == "-0.2億"
    assert result["total"] == "+1.3億"
    assert result["fallback_used"] is True
    assert statuses[-1][1]["fallback_used"] is True


def test_margin_trading_accepts_twse_chinese_fields(monkeypatch) -> None:
    def fake_twse_json(*args, **kwargs):
        return [
            {
                "日期": "20260603",
                "融資今日餘額": "8,123,456",
                "融券今日餘額": "123,456",
            }
        ]

    monkeypatch.setattr(market_data, "twse_json", fake_twse_json)

    result = market_data.get_margin_trading()

    assert result["margin_buy"] == "812.3萬張"
    assert result["short_sell"] == "12.3萬張"
