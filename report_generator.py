"""
report_generator.py — 兩步驟 AI 報告生成 (篩選 → 生成)

Step 1: AI 從大量新聞中篩選 + 分類 + 與 watchlist 交叉比對
Step 2: AI 生成最終報告（盤前/盤後差異化模板）

提供 generate_report() 作為主要入口。
"""

import requests
from datetime import datetime
from groq import Groq


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


# ==========================================
# LLM 呼叫 (Groq 優先, Gemini 備援)
# ==========================================


def _call_llm(
    system: str,
    user: str,
    groq_key: str | None = None,
    gemini_key: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 2000,
) -> str:
    """呼叫 LLM。Groq 優先，Gemini 備援。"""
    # 1. Groq
    if groq_key:
        try:
            client = Groq(api_key=groq_key)
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return completion.choices[0].message.content
        except Exception as e:
            _log(f"Groq Error: {e}")

    # 2. Gemini Fallback
    if gemini_key:
        try:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.0-flash:generateContent?key={gemini_key}"
            )
            payload = {"contents": [{"parts": [{"text": system + "\n\n" + user}]}]}
            res = requests.post(url, json=payload, timeout=60)
            res.raise_for_status()
            data = res.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            _log(f"Gemini Error: {e}")

    return "⚠️ AI 無回應 (請檢查 GROQ_API_KEY / GEMINI_API_KEY)"


# ==========================================
# Step 1: 新聞篩選 + 分類
# ==========================================


def _format_news_for_prompt(news: list[dict]) -> str:
    """將新聞列表格式化為 prompt 素材"""
    lines: list[str] = []
    for i, art in enumerate(news, 1):
        summary = ""
        if art.get("summary"):
            # 截取前 200 字給 AI 參考
            summary = f"\n   摘要: {art['summary'][:200]}"
        lines.append(f"{i}. [{art['source']}] {art['title']}{summary}")
    return "\n".join(lines)


def _step1_filter_news(
    tw_news: list[dict],
    us_news: list[dict],
    watchlist: list[str],
    groq_key: str | None,
    gemini_key: str | None,
) -> str:
    """Step 1: AI 從大量新聞中篩選關鍵新聞，標註 watchlist 關聯"""

    tw_text = _format_news_for_prompt(tw_news) if tw_news else "（無台股新聞）"
    us_text = _format_news_for_prompt(us_news) if us_news else "（無美股新聞）"
    watchlist_str = ", ".join(watchlist[:30]) if watchlist else "未設定"

    system = (
        "你是專業台股研究員。從大量新聞素材中篩選出對台股投資人最重要的新聞。\n\n"
        "【篩選標準 - 按重要性排序】\n"
        "1. 直接影響台股的政策/事件（央行、金管會、重大法規）\n"
        "2. 影響台股權值股的產業新聞（半導體、AI、電子供應鏈）\n"
        "3. 美股/國際市場重大變動（Fed、美股財報、地緣政治）\n"
        "4. 個股重大事件（財報、併購、除權息、法說會）\n"
        "5. 總經數據（GDP、CPI、PMI、就業）\n\n"
        "【輸出規則】\n"
        "- 從所有新聞中篩選 8-12 則最重要的\n"
        "- 每則標註「影響分數」(1-10, 10最重要)\n"
        "- 標註「影響方向」(偏多/偏空/中性)\n"
        "- 若與監控清單股票相關，標註關聯代號\n"
        "- 用繁體中文輸出\n"
        "- 合併相同事件的不同來源報導，取最完整版本"
    )

    user = (
        f"【投資人監控清單】{watchlist_str}\n\n"
        f"【台股新聞 ({len(tw_news)} 則)】\n{tw_text}\n\n"
        f"【國際新聞 ({len(us_news)} 則)】\n{us_text}\n\n"
        "請篩選最重要的 8-12 則新聞，輸出格式：\n"
        "1. (分數/10) [偏多/偏空/中性] 新聞摘要 → 對台股的影響（一句話）"
        "｜關聯: 代號（若有）\n"
        "..."
    )

    _log("🧠 Step 1: AI 篩選新聞...")
    result = _call_llm(
        system, user, groq_key, gemini_key, temperature=0.3, max_tokens=1500
    )
    _log(f"🧠 Step 1 完成 ({len(result)} 字)")
    return result


# ==========================================
# Step 2: 盤前報告
# ==========================================


def _build_pre_market_prompt(
    filtered_news: str,
    market: dict,
    watchlist_str: str,
) -> tuple[str, str]:
    """組裝盤前報告的 system + user prompt"""
    date_str = datetime.now().strftime("%Y/%m/%d")

    tw = market.get("tw_index", {})
    us = market.get("us_indices", {})
    forex = market.get("forex", {})

    # 美股數據文字
    us_lines: list[str] = []
    for name, d in us.items():
        us_lines.append(f"• {name}: {d['price']} ({d['pct']}%)")
    us_text = "\n".join(us_lines) if us_lines else "• 資料取得中"

    system = f"""你是資深台股操盤手，撰寫今日盤前策略筆記。
目標讀者：有經驗的散戶，用手機閱讀。

【核心指令】
1. 語氣模仿法人研究報告，專業精練
2. 重點在「今天該注意什麼」「開盤可能走勢」
3. 用 Emoji 增加可讀性，不使用 Markdown 粗體 (**)
4. 數據直接引用，不可編造
5. 監控清單相關新聞特別提醒
6. 美股大跌→台股可能跳空低開→觀察低接力道；反之亦然

【輸出格式】（嚴格遵守，不可變動結構）

🧭 台股盤前快訊 ({date_str})

📈 市場總覽
• 昨收：{tw.get("price", "N/A")} 點 ({tw.get("pct", "N/A")}%) ｜ 成交值：{tw.get("turnover", "N/A")}
• 台幣：{forex.get("rate", "N/A")} ({forex.get("chg", "N/A")})

🇺🇸 美股收盤
{us_text}

🔑 今日關鍵 (3-4 點)
1. (最重要的觀察，影響今日台股開盤的事件)
2. ...

🔍 焦點個股 (3-5 檔，優先台股)
• 代號 名稱：(事件) ｜ 預期影響

⚡ 重要事件評分 Top5
• (分數/10) 事件描述

📋 操作策略 (2-3 句)
• (今日開盤建議)

⚠️ 免責聲明
• 本報告由 AI 自動生成，僅供參考，不構成投資建議"""

    user = (
        f"【監控清單】{watchlist_str}\n\n"
        f"【AI 篩選重要新聞】\n{filtered_news}\n\n"
        "請根據以上資訊撰寫盤前快訊。"
    )

    return system, user


# ==========================================
# Step 2: 盤後報告
# ==========================================


def _build_post_market_prompt(
    filtered_news: str,
    market: dict,
    watchlist_str: str,
) -> tuple[str, str]:
    """組裝盤後報告的 system + user prompt"""
    date_str = datetime.now().strftime("%Y/%m/%d")

    tw = market.get("tw_index", {})
    us = market.get("us_indices", {})
    forex = market.get("forex", {})
    inst = market.get("institutional", {})
    margin = market.get("margin", {})

    us_lines: list[str] = []
    for name, d in us.items():
        us_lines.append(f"• {name}: {d['price']} ({d['pct']}%)")
    us_text = "\n".join(us_lines) if us_lines else "• 資料取得中"

    system = f"""你是資深台股操盤手，撰寫今日盤後操盤筆記。
目標讀者：有經驗的散戶，用手機閱讀。

【核心指令】
1. 語氣模仿法人研究報告，用「營收動能、庫存調整、本益比評價、資金輪動」等專業詞彙
2. 重點在「今天發生了什麼」「明天要注意什麼」
3. 用 Emoji 增加可讀性，不使用 Markdown 粗體 (**)
4. 數據直接引用，不可編造
5. 監控清單相關新聞特別標註

【輸出格式】（嚴格遵守）

📅 台股盤後筆記 ({date_str})

📈 盤勢回顧
• 收盤：{tw.get("price", "N/A")} 點 ({tw.get("pct", "N/A")}%) ｜ 成交值：{tw.get("turnover", "N/A")}
• 台幣：{forex.get("rate", "N/A")} ({forex.get("chg", "N/A")})
• 盤勢：(一句話描述今日走勢特徵)

🏦 法人動態
• 外資：{inst.get("foreign", "N/A")} ｜ 投信：{inst.get("trust", "N/A")} ｜ 自營：{inst.get("dealer", "N/A")}
• 融資餘額：{margin.get("margin_buy", "N/A")} ｜ 融券：{margin.get("short_sell", "N/A")}
• 法人動向解讀：(一句話，例如「外資連 N 日買超，資金偏多」)

🇺🇸 美股動態
{us_text}

🔍 今日焦點 (3-5 檔)
• 代號 名稱：(今日表現/事件) ｜ 後續觀察

⚡ 重要事件評分 Top5
• (分數/10) 事件描述

📋 明日策略 (2-3 句)
• (明日操作建議、注意事項)

⚠️ 免責聲明
• 本報告由 AI 自動生成，僅供參考，不構成投資建議"""

    user = (
        f"【監控清單】{watchlist_str}\n\n"
        f"【AI 篩選重要新聞】\n{filtered_news}\n\n"
        "請根據以上資訊撰寫盤後筆記。"
    )

    return system, user


# ==========================================
# 主入口
# ==========================================


def generate_report(
    mode: str,
    tw_news: list[dict],
    us_news: list[dict],
    market: dict,
    watchlist: list[str],
    groq_key: str | None = None,
    gemini_key: str | None = None,
) -> str:
    """
    兩步驟 AI 報告生成。

    Args:
        mode:       "PRE" 或 "POST"
        tw_news:    台股新聞列表 (from news_scraper)
        us_news:    美股新聞列表 (from news_scraper)
        market:     市場數據 (from market_data)
        watchlist:  監控股票代碼列表
        groq_key:   Groq API key
        gemini_key: Gemini API key (備援)

    Returns:
        str: 最終報告文字
    """
    if not groq_key and not gemini_key:
        return "⚠️ 未設定 AI API Key (GROQ_API_KEY / GEMINI_API_KEY)"

    if not tw_news and not us_news:
        return "⚠️ 未抓到任何新聞素材，無法生成報告"

    watchlist_str = ", ".join(watchlist[:30]) if watchlist else "未設定"

    # ── Step 1: 篩選新聞 ──
    filtered_news = _step1_filter_news(
        tw_news, us_news, watchlist, groq_key, gemini_key
    )

    if filtered_news.startswith("⚠️"):
        return filtered_news

    # ── Step 2: 生成報告 ──
    _log("🧠 Step 2: 生成最終報告...")
    if mode == "PRE":
        system, user = _build_pre_market_prompt(filtered_news, market, watchlist_str)
    else:
        system, user = _build_post_market_prompt(filtered_news, market, watchlist_str)

    report = _call_llm(
        system, user, groq_key, gemini_key, temperature=0.5, max_tokens=2000
    )
    _log(f"🧠 Step 2 完成 ({len(report)} 字)")
    return report
