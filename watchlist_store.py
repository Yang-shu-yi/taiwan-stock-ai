import json
import os


DEFAULT_WATCHLIST_FILE = "watchlist.json"


def load_watchlist_file(path: str = DEFAULT_WATCHLIST_FILE) -> list[str]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(c).strip() for c in data if str(c).strip()]
    except Exception:
        return []
    return []


def save_watchlist_file(codes: list[str], path: str = DEFAULT_WATCHLIST_FILE) -> None:
    try:
        normalized = sorted({str(c).strip() for c in codes if str(c).strip()})
        with open(path, "w", encoding="utf-8") as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)
    except Exception:
        return


def parse_numeric_codes(tokens: list[str], valid_codes: set[str]) -> list[str]:
    raw: list[str] = []
    for t in tokens:
        raw.extend([x.strip() for x in str(t).split(",")])

    out: list[str] = []
    for code in raw:
        if code.isdigit() and code in valid_codes:
            out.append(code)
    return out
