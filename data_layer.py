from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
import urllib3


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CACHE_DIR = Path(".cache") / "data"
DEFAULT_TIMEOUT = 10
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_STATUS: dict[str, dict[str, Any]] = {}
LOCAL_TZ = ZoneInfo("Asia/Taipei")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def taiwan_now() -> datetime:
    return datetime.now(LOCAL_TZ)


def _safe_key(key: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in key)


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{_safe_key(key)}.json"


def record_status(
    key: str,
    ok: bool,
    source: str,
    ttl_minutes: int,
    error: str | None = None,
    cached: bool = False,
    trading_date: str | None = None,
    as_of: str | None = None,
    fallback_used: bool | None = None,
    stale_reason: str | None = None,
) -> None:
    local_now = taiwan_now()
    _STATUS[key] = {
        "ok": ok,
        "source": source,
        "updated_at": now_iso(),
        "ttl_minutes": ttl_minutes,
        "cached": cached,
        "error": error,
        "trading_date": trading_date or local_now.strftime("%Y-%m-%d"),
        "as_of": as_of or local_now.isoformat(timespec="seconds"),
        "fallback_used": cached if fallback_used is None else fallback_used,
        "stale_reason": stale_reason,
    }


def get_data_status() -> dict[str, dict[str, Any]]:
    return dict(_STATUS)


def reset_data_status() -> None:
    _STATUS.clear()


def _read_cache(key: str) -> dict[str, Any] | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_fresh(payload: dict[str, Any], ttl_minutes: int) -> bool:
    fetched_at = payload.get("fetched_at")
    if not fetched_at:
        return False
    try:
        ts = datetime.fromisoformat(str(fetched_at))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - ts).total_seconds()
        return age_seconds <= ttl_minutes * 60
    except Exception:
        return False


def _write_cache(key: str, data: Any) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"fetched_at": now_iso(), "data": data}
    _cache_path(key).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def fetch_json(
    key: str,
    url: str,
    ttl_minutes: int,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
    params: dict[str, Any] | None = None,
) -> Any:
    cached = _read_cache(key)
    if cached is not None and _is_fresh(cached, ttl_minutes):
        record_status(
            key,
            True,
            url,
            ttl_minutes,
            cached=True,
            fallback_used=False,
            stale_reason=None,
        )
        return cached.get("data")

    try:
        response = requests.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=timeout,
            verify=verify,
        )
        response.raise_for_status()
        data = response.json()
        _write_cache(key, data)
        record_status(key, True, url, ttl_minutes)
        return data
    except Exception as exc:
        if cached is not None:
            record_status(
                key,
                False,
                url,
                ttl_minutes,
                str(exc),
                cached=True,
                fallback_used=True,
                stale_reason="source_failed_using_cache",
            )
            return cached.get("data")
        record_status(
            key,
            False,
            url,
            ttl_minutes,
            str(exc),
            cached=False,
            fallback_used=False,
            stale_reason="source_failed_no_cache",
        )
        raise


def yahoo_chart(symbol: str, interval: str = "1d", range_: str = "2d") -> dict:
    encoded = symbol.replace("^", "%5E")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
    params = {"interval": interval, "range": range_}
    return fetch_json(
        f"yahoo_{symbol}_{interval}_{range_}",
        url,
        ttl_minutes=15,
        params=params,
    )


def twse_json(key: str, url: str, ttl_minutes: int) -> Any:
    return fetch_json(key, url, ttl_minutes=ttl_minutes, verify=False)


def record_news_status(tw_count: int, us_count: int) -> None:
    ok = tw_count > 0 or us_count > 0
    error = None if ok else "no news items fetched"
    record_status("news", ok, "rss/news_scraper", 30, error=error)
