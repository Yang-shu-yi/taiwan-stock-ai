import json
import os
import time
from typing import Any


DEFAULT_ALERTS_FILE = "alerts.jsonl"


def append_alert(alert: dict[str, Any], path: str = DEFAULT_ALERTS_FILE) -> None:
    try:
        record = dict(alert)
        record.setdefault("ts", int(time.time()))
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        return


def read_recent_alerts(
    limit: int = 100, path: str = DEFAULT_ALERTS_FILE
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    if not os.path.exists(path):
        return []

    out: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []

    return out[-limit:]
