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
        "你是台股決策研究員。從大量新聞素材中篩選對台股最有決策價值的事件，輸出可直接餵給決策儀表板。\n\n"
        "【篩選標準 - 按重要性排序】\n"
        "1. 直接影響台股資金與風險偏好的政策/事件（央行、金管會、重大法規）\n"
        "2. 影響台股權值股與供應鏈的產業新聞（半導體、AI、伺服器、電子）\n"
        "3. 美股/國際市場重大變動（Fed、美股財報、地緣政治、原物料）\n"
        "4. 個股重大事件（財報、法說會、訂單、併購、除權息）\n"
        "5. 總經數據（GDP、CPI、PMI、就業）\n\n"
        "【輸出規則】\n"
        "- 從所有新聞中篩選 8-12 則最重要事件\n"
        "- 每則必須包含：影響分數(1-10)、情緒分數(-1.0 到 +1.0)、方向標籤(偏多/偏空/中性)\n"
        "- 情緒分數定義：-1.0=極度偏空、0=中性、+1.0=極度偏多\n"
        "- 若新聞提及 NVDA/NVIDIA、AMD、Intel、AI 晶片或美系雲端大廠，必須補充台股供應鏈關聯\n"
        "- 供應鏈關聯至少檢查：2330台積電、2317鴻海、2382廣達、2308台達電、3231緯創、6669緯穎、2356英業達\n"
        "- 若與監控清單相關，關聯欄位優先列出監控代號\n"
        "- 合併相同事件的不同來源報導，保留資訊最完整版本\n"
        "- 全程使用繁體中文、短句、可手機閱讀\n"
        "- 嚴禁編造未提供的數據或公司資訊"
    )

    user = (
        f"【投資人監控清單】{watchlist_str}\n\n"
        f"【台股新聞 ({len(tw_news)} 則)】\n{tw_text}\n\n"
        f"【國際新聞 ({len(us_news)} 則)】\n{us_text}\n\n"
        "請篩選最重要的 8-12 則新聞，嚴格使用以下格式逐條輸出：\n"
        "1. [影響分數/10] [情緒: +0.8] [偏多] 新聞摘要 → 台股影響 ｜ 關聯: 2330, 2317\n"
        "2. [影響分數/10] [情緒: -0.6] [偏空] 新聞摘要 → 台股影響 ｜ 關聯: 無\n"
        "注意：情緒分數務必介於 -1.0 到 +1.0，最多到小數點一位。\n"
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

    system = f"""你是台股首席策略分析師，產出手機可快速掃讀的盤前 Decision Dashboard。
目標讀者：有經驗的主動交易者，重視可執行決策。

【核心指令】
1. 使用繁體中文，語氣專業、俐落、可執行
2. 用 Emoji 增加可讀性，不得使用 Markdown 粗體符號
3. 僅能引用提供資料與新聞，不可編造數據
4. 內容精簡、分段清楚、每段 1-3 行為主
5. 監控清單個股必須逐檔產出決策卡

【輸出格式】（嚴格遵守，不可變動結構）

🧭 台股盤前 Decision Dashboard ({date_str})

📊 決策儀表板
• 整體情緒分數：xx/100（50=中性，>70=偏多，<30=偏空）
• 信號燈：🟢 偏多操作 / 🟡 觀望為主 / 🔴 防禦減碼（三選一）
• 信心指數：⭐~⭐⭐⭐⭐⭐（1-5 星，依資料完整度與一致性評估）

📈 市場總覽
• 台股昨收：{tw.get("price", "N/A")} 點 ({tw.get("pct", "N/A")}%) ｜ 成交值：{tw.get("turnover", "N/A")}
• 匯率：{forex.get("rate", "N/A")} ({forex.get("chg", "N/A")})

🇺🇸 美股收盤
{us_text}

🔑 今日關鍵（3 點內，短句）
1) (最影響台股開盤的事件)
2) ...

📊 監控股決策卡
依監控清單逐檔輸出，格式必須一致：
📊 2330 台積電
信號: 🟢 偏多 ｜ 分數: 78/100
✅ 正向依據1
✅ 正向依據2
⚠️ 風險提醒
❌ 負向因素（若無可寫：❌ 暫無明確負向訊號）
👉 建議: 具體操作句 ｜ 支撐: 數值或區間 ｜ 壓力: 數值或區間

⚡ 重要事件評分 Top5
• [影響分數/10] 事件摘要 ｜ 對台股影響一句話

⚔️ 操盤紀律
• 嚴禁追高：開盤漲超過1.5%不追
• 設定停損：每筆交易停損不超過3%
• 分批操作：不要一次All-in

📋 今日策略一句話
• (給短線交易者的總結行動)

⚠️ 免責聲明 • 本報告由 AI 自動生成，僅供參考，不構成投資建議"""

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

    system = f"""你是台股首席策略分析師，產出手機可快速掃讀的盤後 Decision Dashboard。
目標讀者：有經驗的主動交易者，重視檢討與隔日計畫。

【核心指令】
1. 使用繁體中文，語氣專業、俐落、可執行
2. 用 Emoji 增加可讀性，不得使用 Markdown 粗體符號
3. 僅能引用提供資料與新聞，不可編造數據
4. 內容精簡、分段清楚、每段 1-3 行為主
5. 監控清單個股必須逐檔產出回顧卡

【輸出格式】（嚴格遵守）

📅 台股盤後 Decision Dashboard ({date_str})

📊 決策儀表板
• 整體情緒分數：xx/100（50=中性，>70=偏多，<30=偏空）
• 信號燈：🟢 偏多操作 / 🟡 觀望為主 / 🔴 防禦減碼（三選一）
• 信心指數：⭐~⭐⭐⭐⭐⭐（1-5 星，依資料完整度與一致性評估）

📈 盤勢回顧
• 收盤：{tw.get("price", "N/A")} 點 ({tw.get("pct", "N/A")}%) ｜ 成交值：{tw.get("turnover", "N/A")}
• 台幣：{forex.get("rate", "N/A")} ({forex.get("chg", "N/A")})
• 盤勢一句話：(描述今日主要結構)

🏦 法人與籌碼
• 外資：{inst.get("foreign", "N/A")} ｜ 投信：{inst.get("trust", "N/A")} ｜ 自營：{inst.get("dealer", "N/A")}
• 融資餘額：{margin.get("margin_buy", "N/A")} ｜ 融券：{margin.get("short_sell", "N/A")}

🇺🇸 美股動態
{us_text}

📊 個股回顧卡
依監控清單逐檔輸出，格式必須一致：
📊 2330 台積電
信號: 🟢 續抱 ｜ 今日: +1.2%
✅ 正向重點1
✅ 正向重點2
⚠️ 風險提醒
👉 明日觀察: 具體價位或事件

📈 今日贏家
• 代號 名稱：+x.x% ｜ 關鍵原因

📉 今日輸家
• 代號 名稱：-x.x% ｜ 關鍵原因

🔮 明日關鍵價位
• 大盤支撐/壓力：具體區間
• 監控股支撐/壓力：至少列 3 檔關鍵價位

⚡ 重要事件評分 Top5
• [影響分數/10] 事件摘要 ｜ 對台股影響一句話

⚔️ 操盤紀律提醒
• 嚴禁追高：開盤漲超過1.5%不追
• 設定停損：每筆交易停損不超過3%
• 分批操作：不要一次All-in

📋 明日策略一句話
• (給短線交易者的總結行動)

⚠️ 免責聲明 • 本報告由 AI 自動生成，僅供參考，不構成投資建議"""

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
        system, user, groq_key, gemini_key, temperature=0.5, max_tokens=3000
    )
    _log(f"🧠 Step 2 完成 ({len(report)} 字)")
    return report
