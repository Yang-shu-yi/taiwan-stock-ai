from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class ConfigIssue:
    level: str
    message: str


def validate_runtime_config() -> list[ConfigIssue]:
    issues: list[ConfigIssue] = []

    if env_flag("ENABLE_REPORT_TELEGRAM", True):
        if not os.getenv("REPORT_TELEGRAM_BOT_TOKEN"):
            issues.append(ConfigIssue("ERROR", "缺少 REPORT_TELEGRAM_BOT_TOKEN，報告 Telegram 不會發送。"))
        if not os.getenv("REPORT_TELEGRAM_CHAT_ID"):
            issues.append(ConfigIssue("ERROR", "缺少 REPORT_TELEGRAM_CHAT_ID，報告 Telegram 不會發送。"))

    if env_flag("ENABLE_LINE", False):
        if not os.getenv("LINE_CHANNEL_TOKEN"):
            issues.append(ConfigIssue("ERROR", "缺少 LINE_CHANNEL_TOKEN，LINE 不會發送。"))
        if not os.getenv("LINE_TARGET_ID"):
            issues.append(ConfigIssue("ERROR", "缺少 LINE_TARGET_ID，LINE 不會發送。"))

    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    service_account = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    if spreadsheet_id:
        if not service_account:
            issues.append(ConfigIssue("WARN", "已設定 SPREADSHEET_ID，但缺少 GOOGLE_SERVICE_ACCOUNT_FILE，將略過 Google Sheets。"))
        elif not Path(service_account).exists():
            issues.append(ConfigIssue("WARN", f"找不到 Google service account 檔案: {service_account}，將略過 Google Sheets。"))

    if os.getenv("ENABLE_TELEGRAM") or os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_CHAT_ID"):
        issues.append(ConfigIssue("WARN", "偵測到舊 TELEGRAM_* 設定；報告發送只使用 REPORT_TELEGRAM_*。"))

    if not os.getenv("REPORT_DASHBOARD_URL"):
        issues.append(ConfigIssue("WARN", "缺少 REPORT_DASHBOARD_URL，報告尾端不會附 Dashboard 連結。"))

    return issues
