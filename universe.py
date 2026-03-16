import os

import twstock


DEFAULT_TW_CORE_CODES = [
    "2330",
    "2317",
    "2454",
    "2308",
    "2303",
    "3711",
    "2382",
    "3231",
    "6669",
    "3017",
    "2376",
    "2357",
    "2345",
    "2327",
    "3661",
    "3443",
    "3034",
    "3008",
    "2049",
    "3019",
    "3023",
    "3035",
    "6415",
    "6531",
    "3596",
    "6187",
    "2451",
    "2408",
    "2301",
    "2379",
    "3037",
    "2603",
    "2615",
    "2609",
    "2002",
    "2207",
    "1519",
    "1301",
    "1303",
    "2881",
    "2882",
    "2884",
    "2885",
    "2886",
    "2891",
    "2892",
    "5880",
]

DEFAULT_US_CONTEXT_SYMBOLS = [
    "SPY",
    "QQQ",
    "DIA",
    "IWM",
    "SOXX",
    "NVDA",
    "AVGO",
    "AMD",
    "MU",
    "TSM",
    "MSFT",
    "AAPL",
    "AMZN",
    "META",
    "GOOGL",
    "TSLA",
]

THEME_BY_CODE = {
    "2330": "半導體",
    "2454": "IC設計",
    "2308": "電源/散熱",
    "2303": "半導體",
    "3711": "半導體封測",
    "2317": "AI伺服器",
    "2382": "AI伺服器",
    "3231": "AI伺服器",
    "6669": "AI伺服器",
    "3017": "電源/散熱",
    "2376": "AI伺服器",
    "2357": "AI伺服器",
    "2345": "網通",
    "2327": "被動元件",
    "3661": "IC設計",
    "3443": "IC設計",
    "3034": "IC設計",
    "3008": "光學",
    "2049": "自動化",
    "3019": "光學",
    "3023": "工業連接",
    "3035": "IC設計",
    "6415": "IC設計",
    "3037": "PCB/ABF",
    "6531": "記憶體",
    "3596": "網通",
    "6187": "半導體設備",
    "2451": "記憶體",
    "2408": "記憶體",
    "2301": "電源/散熱",
    "2379": "IC設計",
    "1303": "塑化",
    "2603": "航運",
    "2615": "航運",
    "2609": "航運",
    "2002": "鋼鐵",
    "2207": "汽車",
    "1519": "重電",
    "1301": "塑化",
    "2881": "金融",
    "2882": "金融",
    "2884": "金融",
    "2885": "金融",
    "2886": "金融",
    "2891": "金融",
    "2892": "金融",
    "5880": "金融",
}


def _split_csv(raw: str) -> list[str]:
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def get_tw_core_codes() -> list[str]:
    codes = list(DEFAULT_TW_CORE_CODES)
    extra = os.getenv("TW_EXTRA_CODES", "").strip()
    if extra:
        codes.extend(_split_csv(extra))
    valid = [code for code in _unique(codes) if code.isdigit() and code in twstock.codes]
    max_count = int(os.getenv("TW_SCAN_LIMIT", str(len(valid))))
    return valid[:max_count]


def get_us_context_symbols() -> list[str]:
    override = os.getenv("US_CONTEXT_SYMBOLS", "").strip()
    symbols = _split_csv(override) if override else list(DEFAULT_US_CONTEXT_SYMBOLS)
    max_count = int(os.getenv("US_CONTEXT_LIMIT", str(len(symbols))))
    return _unique(symbols)[:max_count]


def tw_code_to_yahoo_symbol(code: str) -> str:
    market = twstock.codes[code].market
    suffix = ".TW" if market == "上市" else ".TWO"
    return f"{code}{suffix}"


def get_tw_name(code: str) -> str:
    return twstock.codes[code].name if code in twstock.codes else code


def get_theme_for_code(code: str) -> str:
    return THEME_BY_CODE.get(code, "電子")
