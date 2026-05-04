import os

import requests
from dotenv import load_dotenv


load_dotenv()


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


ENABLE_REPORT_TELEGRAM = _env_flag("ENABLE_REPORT_TELEGRAM", True)
ENABLE_LINE = _env_flag("ENABLE_LINE", False)
REPORT_NOTIFY_ERRORS = _env_flag("REPORT_NOTIFY_ERRORS", False)
REPORT_DASHBOARD_URL = os.getenv(
    "REPORT_DASHBOARD_URL",
    "https://taiwan-stock-ai-cmignppyqbx3qyslpthtnz.streamlit.app/",
).strip()

LINE_CHANNEL_TOKEN = os.getenv("LINE_CHANNEL_TOKEN")
LINE_TARGET_ID = os.getenv("LINE_TARGET_ID")

REPORT_TELEGRAM_BOT_TOKEN = os.getenv("REPORT_TELEGRAM_BOT_TOKEN")
REPORT_TELEGRAM_CHAT_ID = os.getenv("REPORT_TELEGRAM_CHAT_ID")


def _send_telegram_message(message: str, token: str, chat_id: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()


def _with_dashboard_link(message: str) -> str:
    if not REPORT_DASHBOARD_URL:
        return message
    if REPORT_DASHBOARD_URL in message:
        return message
    suffix = f"\n\nDashboard: {REPORT_DASHBOARD_URL}"
    return f"{message.rstrip()}{suffix}"


def send_report_message(message: str) -> None:
    if (
        not ENABLE_REPORT_TELEGRAM
        or not REPORT_TELEGRAM_BOT_TOKEN
        or not REPORT_TELEGRAM_CHAT_ID
    ):
        return
    _send_telegram_message(message, REPORT_TELEGRAM_BOT_TOKEN, REPORT_TELEGRAM_CHAT_ID)


def send_report_error(message: str) -> None:
    if not REPORT_NOTIFY_ERRORS:
        return
    send_report_message(message)


def send_line_message(message: str) -> None:
    if not ENABLE_LINE or not LINE_CHANNEL_TOKEN or not LINE_TARGET_ID:
        return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "to": LINE_TARGET_ID,
        "messages": [{"type": "text", "text": message[:4500]}],
    }
    response = requests.post(url, headers=headers, json=payload, timeout=10)
    response.raise_for_status()


def notify_report(message: str) -> None:
    final_message = _with_dashboard_link(message)
    send_report_message(final_message)
    send_line_message(final_message)
