"""Export a static Taiwan stock search index for the Vercel dashboard."""

from __future__ import annotations

import json
from pathlib import Path

import twstock


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "web" / "data" / "tw_stock_index.json"


def build_index() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for code, info in twstock.codes.items():
        code_text = str(code)
        stock_type = getattr(info, "type", "") or ""
        if not code_text.isdigit() or len(code_text) not in (4, 5):
            continue
        if stock_type != "股票":
            continue
        rows.append(
            {
                "code": code_text,
                "name": getattr(info, "name", "") or "",
                "market": getattr(info, "market", "") or "",
                "type": stock_type,
                "group": getattr(info, "group", "") or "",
            }
        )
    return sorted(rows, key=lambda item: item["code"])


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(build_index(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
