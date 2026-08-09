import market_data


def test_yahoo_quote_records_actual_market_date(monkeypatch) -> None:
    market_time = market_data.datetime(
        2026,
        7,
        23,
        13,
        30,
        tzinfo=market_data.LOCAL_TZ,
    ).timestamp()
    monkeypatch.setattr(
        market_data,
        "yahoo_chart",
        lambda *args, **kwargs: {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "regularMarketPrice": 44851,
                            "previousClose": 44825,
                            "regularMarketTime": market_time,
                        }
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        market_data,
        "get_data_status",
        lambda: {
            "yahoo_^TWII_1d_2d": {
                "ok": True,
                "source": "yahoo",
                "ttl_minutes": 15,
                "cached": True,
                "fallback_used": True,
                "stale_reason": "fresh_cache",
            }
        },
    )
    statuses = []
    monkeypatch.setattr(
        market_data,
        "record_status",
        lambda *args, **kwargs: statuses.append((args, kwargs)),
    )

    result = market_data._yahoo_quote("^TWII")

    assert result["trading_date"] == "2026-07-23"
    assert statuses[-1][1]["trading_date"] == "2026-07-23"
    assert statuses[-1][1]["cached"] is True


def test_tw_index_records_actual_turnover_date(monkeypatch) -> None:
    monkeypatch.setattr(
        market_data,
        "_yahoo_quote",
        lambda *args, **kwargs: {
            "price": 44851.0,
            "chg": 25.0,
            "pct": 0.06,
            "trading_date": "2026-07-23",
            "as_of": "2026-07-23T13:30:00+08:00",
            "market_state": "CLOSED",
        },
    )
    monkeypatch.setattr(
        market_data,
        "twse_json",
        lambda *args, **kwargs: [{"Date": "1150722", "TradeValue": "1025958396323"}],
    )
    monkeypatch.setattr(
        market_data,
        "get_data_status",
        lambda: {
            "twse_turnover": {
                "ok": True,
                "source": "twse",
                "ttl_minutes": 15,
                "cached": False,
                "fallback_used": False,
            }
        },
    )
    statuses = []
    monkeypatch.setattr(
        market_data,
        "record_status",
        lambda *args, **kwargs: statuses.append((args, kwargs)),
    )

    result = market_data.get_tw_index()

    assert result["turnover"] == "10260億"
    assert statuses[-1][1]["trading_date"] == "2026-07-22"


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
