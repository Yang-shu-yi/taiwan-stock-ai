import os
import time
from typing import Any, Optional

import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from alert_store import read_recent_alerts
from watchlist_store import (
    DEFAULT_WATCHLIST_FILE,
    load_watchlist_file,
    save_watchlist_file,
)


load_dotenv()

APP_API_KEY = os.getenv("APP_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def require_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> None:
    if not APP_API_KEY:
        raise HTTPException(status_code=500, detail="APP_API_KEY not configured")
    if not x_api_key or x_api_key != APP_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


def send_telegram_message(msg: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise HTTPException(status_code=500, detail="Telegram not configured")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    try:
        res = requests.post(url, json=payload, timeout=10)
        res.raise_for_status()
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to send Telegram message")


app = FastAPI(title="taiwan-stock-ai API")


class CodesPayload(BaseModel):
    codes: list[str] = Field(default_factory=list)


class MessagePayload(BaseModel):
    message: str


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "ts": int(time.time())}


@app.get("/watchlist", dependencies=[Depends(require_api_key)])
def get_watchlist() -> dict[str, Any]:
    return {"codes": load_watchlist_file(DEFAULT_WATCHLIST_FILE)}


@app.put("/watchlist", dependencies=[Depends(require_api_key)])
def put_watchlist(payload: CodesPayload) -> dict[str, Any]:
    save_watchlist_file(payload.codes, DEFAULT_WATCHLIST_FILE)
    return {"codes": load_watchlist_file(DEFAULT_WATCHLIST_FILE)}


@app.post("/watchlist/add", dependencies=[Depends(require_api_key)])
def add_watchlist(payload: CodesPayload) -> dict[str, Any]:
    current = load_watchlist_file(DEFAULT_WATCHLIST_FILE)
    merged = sorted({*current, *payload.codes})
    save_watchlist_file(merged, DEFAULT_WATCHLIST_FILE)
    return {"codes": merged}


@app.post("/watchlist/del", dependencies=[Depends(require_api_key)])
def del_watchlist(payload: CodesPayload) -> dict[str, Any]:
    current = load_watchlist_file(DEFAULT_WATCHLIST_FILE)
    to_remove = {c.strip() for c in payload.codes if c.strip()}
    new_list = [c for c in current if c not in to_remove]
    save_watchlist_file(new_list, DEFAULT_WATCHLIST_FILE)
    return {"codes": new_list}


@app.get("/alerts", dependencies=[Depends(require_api_key)])
def get_alerts(limit: int = 100) -> dict[str, Any]:
    return {"alerts": read_recent_alerts(limit=limit)}


@app.post("/notify/test", dependencies=[Depends(require_api_key)])
def notify_test(payload: MessagePayload) -> dict[str, Any]:
    send_telegram_message(payload.message)
    return {"ok": True}
