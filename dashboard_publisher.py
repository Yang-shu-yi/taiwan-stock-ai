from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo("Asia/Taipei")
DEFAULT_BLOB_PATH = "dashboard/latest.json"


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


def dashboard_publish_enabled() -> bool:
    token_present = bool(os.getenv("BLOB_READ_WRITE_TOKEN", "").strip())
    return _env_flag("ENABLE_DASHBOARD_PUBLISH", token_present) and token_present


def publish_dashboard_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Publish the latest formal snapshot without exposing the write token.

    The caller owns failure handling so a dashboard outage never blocks report
    delivery. Research and dry-run callers must not invoke this function.
    """
    if not dashboard_publish_enabled():
        return {"ok": False, "status": "disabled"}
    if not snapshot.get("updated_at") or not snapshot.get("mode"):
        raise ValueError("dashboard snapshot is missing updated_at or mode")

    from vercel.blob import BlobClient

    token = os.getenv("BLOB_READ_WRITE_TOKEN", "").strip()
    pathname = os.getenv("DASHBOARD_BLOB_PATH", DEFAULT_BLOB_PATH).strip() or DEFAULT_BLOB_PATH
    published_at = datetime.now(LOCAL_TZ).isoformat(timespec="seconds")
    payload = dict(snapshot)
    payload["publication"] = {
        "provider": "vercel_blob",
        "pathname": pathname,
        "published_at": published_at,
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    result = BlobClient(token=token).put(
        pathname,
        body,
        access="public",
        content_type="application/json; charset=utf-8",
        add_random_suffix=False,
        overwrite=True,
        cache_control_max_age=60,
        multipart=False,
    )
    return {
        "ok": True,
        "status": "published",
        "url": str(result.url),
        "pathname": pathname,
        "published_at": published_at,
    }
