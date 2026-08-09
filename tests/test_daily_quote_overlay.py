import pandas as pd

from daily_quote_overlay import (
    overlay_latest_quote,
    parse_tpex_daily_quotes,
    parse_twse_daily_quotes,
)


def test_parse_twse_daily_quote_table() -> None:
    payload = {
        "stat": "OK",
        "date": "20260723",
        "tables": [
            {
                "fields": [
                    "證券代號",
                    "證券名稱",
                    "成交股數",
                    "開盤價",
                    "最高價",
                    "最低價",
                    "收盤價",
                ],
                "data": [
                    ["1301", "台塑", "60,422,391", "61.0", "64.0", "60.5", "63.0"],
                ],
            }
        ],
    }

    quotes = parse_twse_daily_quotes(payload, "2026-07-23")

    assert quotes["1301"]["date"] == "2026-07-23"
    assert quotes["1301"]["Close"] == 63.0
    assert quotes["1301"]["Volume"] == 60_422_391


def test_parse_tpex_roc_date_and_quote_fields() -> None:
    quotes = parse_tpex_daily_quotes(
        [
            {
                "Date": "1150723",
                "SecuritiesCompanyCode": "6274",
                "Open": "120.0",
                "High": "124.0",
                "Low": "119.0",
                "Close": "123.0",
                "TradingShares": "1000000",
            }
        ]
    )

    assert quotes["6274"]["date"] == "2026-07-23"
    assert quotes["6274"]["Close"] == 123.0


def test_overlay_appends_official_close_when_yahoo_is_one_day_late() -> None:
    index = pd.DatetimeIndex(
        ["2026-07-21", "2026-07-22"],
        tz="Asia/Taipei",
    )
    history = pd.DataFrame(
        {
            "Open": [60.0, 62.0],
            "High": [62.0, 64.0],
            "Low": [59.0, 61.0],
            "Close": [61.0, 63.5],
            "Volume": [1_000_000, 1_200_000],
            "Dividends": [0.0, 0.0],
            "Stock Splits": [0.0, 0.0],
        },
        index=index,
    )
    quote = {
        "date": "2026-07-23",
        "Open": 64.0,
        "High": 66.5,
        "Low": 63.1,
        "Close": 66.2,
        "Volume": 2_000_000,
    }

    result = overlay_latest_quote(history, quote)

    assert result is not None
    assert result.index[-1].date().isoformat() == "2026-07-23"
    assert result.iloc[-1]["Close"] == 66.2
    assert result.iloc[-1]["Volume"] == 2_000_000
