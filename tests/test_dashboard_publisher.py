import json
from types import SimpleNamespace

import dashboard_publisher


def test_publish_disabled_without_token(monkeypatch) -> None:
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.setenv("ENABLE_DASHBOARD_PUBLISH", "true")

    result = dashboard_publisher.publish_dashboard_snapshot(
        {"updated_at": "2026-07-22 08:35:00", "mode": "PRE"}
    )

    assert result == {"ok": False, "status": "disabled"}


def test_publish_writes_public_json_with_short_cache(monkeypatch) -> None:
    calls = []

    class FakeBlobClient:
        def __init__(self, token: str):
            assert token == "secret-token"

        def put(self, pathname, body, **kwargs):
            calls.append((pathname, json.loads(body), kwargs))
            return SimpleNamespace(url="https://blob.example/dashboard/latest.json")

    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "secret-token")
    monkeypatch.setenv("ENABLE_DASHBOARD_PUBLISH", "true")
    monkeypatch.setenv("DASHBOARD_BLOB_PATH", "dashboard/latest.json")
    monkeypatch.setattr("vercel.blob.BlobClient", FakeBlobClient)

    result = dashboard_publisher.publish_dashboard_snapshot(
        {"updated_at": "2026-07-22 08:35:00", "mode": "PRE", "market": {}}
    )

    assert result["ok"] is True
    pathname, payload, options = calls[0]
    assert pathname == "dashboard/latest.json"
    assert payload["publication"]["provider"] == "vercel_blob"
    assert payload["publication"]["pathname"] == "dashboard/latest.json"
    assert options["overwrite"] is True
    assert options["cache_control_max_age"] == 60
    assert options["access"] == "public"
