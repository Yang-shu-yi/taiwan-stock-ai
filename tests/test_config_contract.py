from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_env_example_uses_report_bot_contract() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "REPORT_TELEGRAM_BOT_TOKEN" in text
    assert "REPORT_TELEGRAM_CHAT_ID" in text
    assert "ENABLE_REPORT_TELEGRAM=true" in text
    assert "\nTELEGRAM_BOT_TOKEN=" not in f"\n{text}"
    assert "DAILY_CANDIDATES_FILE=runtime/daily_candidates.json" in text
    assert "REPORT_DASHBOARD_URL=https://taiwan-stock-ai-pi.vercel.app/" in text
    assert "VERCEL_SNAPSHOT_URL=" in text
    assert "BLOB_READ_WRITE_TOKEN=" in text
    assert "ENABLE_SMALL_MID_RADAR=true" in text
    assert "SMALL_MID_PROMOTE_LIMIT=2" in text


def test_sample_snapshot_fixture_exists() -> None:
    assert (ROOT / "tests" / "fixtures" / "sample_daily_candidates.json").exists()


def test_workflow_is_dry_run_only() -> None:
    text = (ROOT / ".github" / "workflows" / "daily_scan.yml").read_text(encoding="utf-8")
    assert 'DRY_RUN: "true"' in text
    assert 'ENABLE_REPORT_TELEGRAM: "false"' in text
    assert 'ENABLE_LINE: "false"' in text
    assert "git add daily_candidates.json" not in text
    assert "cron:" not in text
    assert "ENABLE_TELEGRAM" not in text
    assert "TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}" not in text
    assert "npm run build" in text
