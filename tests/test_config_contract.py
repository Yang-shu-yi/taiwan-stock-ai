from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_env_example_uses_report_bot_contract() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "REPORT_TELEGRAM_BOT_TOKEN" in text
    assert "REPORT_TELEGRAM_CHAT_ID" in text
    assert "ENABLE_REPORT_TELEGRAM=true" in text
    assert "\nTELEGRAM_BOT_TOKEN=" not in f"\n{text}"


def test_workflow_uses_report_bot_and_line_contract() -> None:
    text = (ROOT / ".github" / "workflows" / "daily_scan.yml").read_text(encoding="utf-8")
    assert "REPORT_TELEGRAM_BOT_TOKEN" in text
    assert "REPORT_TELEGRAM_CHAT_ID" in text
    assert "LINE_CHANNEL_TOKEN" in text
    assert "ENABLE_TELEGRAM" not in text
    assert "TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}" not in text
