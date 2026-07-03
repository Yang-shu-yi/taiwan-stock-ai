"""
news_scraper.py — 多來源新聞抓取 + 內文摘要 + 去重

提供 fetch_all_news() 作為主要入口，回傳去重後的新聞列表。
每則新聞包含 title, summary (內文前 N 字), source, url, published。
"""

import re
from datetime import datetime
from difflib import SequenceMatcher

import feedparser
import requests
from bs4 import BeautifulSoup


# ==========================================
# RSS 來源設定
# ==========================================

RSS_SOURCES_TW = {
    "鉅亨": "https://news.google.com/rss/search?q=site:news.cnyes.com%20when:1d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "科技新報財經": "https://finance.technews.tw/feed/",
    "Yahoo財經": "https://tw.stock.yahoo.com/rss?category=tw-market",
    "Google台股": "https://news.google.com/rss/search?q=%E5%8F%B0%E8%82%A1+when:1d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "經濟日報": "https://money.udn.com/rssfeed/news/1001/5591/0",
}

RSS_SOURCES_US = {
    "CNBC": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_SUMMARY_MAX_CHARS = 500


def _log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))


# ==========================================
# RSS 抓取
# ==========================================


def fetch_rss(url: str, source: str, max_items: int = 10) -> list[dict]:
    """解析單一 RSS 來源，回傳 [{title, url, source, published, summary}]"""
    try:
        feed = feedparser.parse(url)
        articles: list[dict] = []
        for entry in feed.entries[:max_items]:
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            link = (entry.get("link") or "").strip()
            published = entry.get("published", "")
            articles.append(
                {
                    "title": title,
                    "url": link,
                    "source": source,
                    "published": published,
                    "summary": "",
                }
            )
        return articles
    except Exception as e:
        _log(f"RSS Error ({source}): {e}")
        return []


# ==========================================
# 內文擷取
# ==========================================


def extract_article_content(url: str, max_chars: int = _SUMMARY_MAX_CHARS) -> str:
    """嘗試抓取文章 URL，回傳內文前 N 字。失敗回空字串。"""
    if not url:
        return ""
    try:
        res = requests.get(url, headers=_HEADERS, timeout=8, allow_redirects=True)
        res.raise_for_status()

        # 嘗試用 lxml，fallback 到 html.parser
        try:
            soup = BeautifulSoup(res.text, "lxml")
        except Exception:
            soup = BeautifulSoup(res.text, "html.parser")

        # 移除非內容元素
        for tag in soup(
            ["script", "style", "nav", "header", "footer", "aside", "iframe"]
        ):
            tag.decompose()

        # 嘗試常見文章容器
        article = (
            soup.find("article")
            or soup.find(
                "div",
                class_=re.compile(r"article|content|story|entry", re.I),
            )
            or soup.find("main")
        )
        target = article if article else soup.body
        if not target:
            return ""

        paragraphs = target.find_all("p")
        text = " ".join(
            p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)
        )

        # 清理多餘空白
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars] if text else ""
    except Exception:
        return ""


# ==========================================
# 去重
# ==========================================


def _title_similarity(a: str, b: str) -> float:
    """計算兩個標題的相似度 (0~1)"""
    return SequenceMatcher(None, a, b).ratio()


def deduplicate_news(articles: list[dict], threshold: float = 0.6) -> list[dict]:
    """依標題相似度去重。保留最早出現的版本。"""
    unique: list[dict] = []
    for art in articles:
        is_dup = False
        for existing in unique:
            if _title_similarity(art["title"], existing["title"]) > threshold:
                is_dup = True
                break
        if not is_dup:
            unique.append(art)
    return unique


# ==========================================
# 主入口
# ==========================================


def fetch_all_news(
    max_per_source: int = 8,
    fetch_content: bool = True,
    content_max_chars: int = _SUMMARY_MAX_CHARS,
) -> tuple[list[dict], list[dict]]:
    """
    抓取所有來源新聞，擷取內文，去重後回傳。

    Returns:
        (tw_news, us_news): 兩組去重後的新聞列表，
        每則包含 title, summary, source, url, published
    """
    tw_articles: list[dict] = []
    us_articles: list[dict] = []

    # 台股新聞
    for source, url in RSS_SOURCES_TW.items():
        articles = fetch_rss(url, source, max_items=max_per_source)
        _log(f"📰 {source}: 抓到 {len(articles)} 則")
        tw_articles.extend(articles)

    # 美股新聞
    for source, url in RSS_SOURCES_US.items():
        articles = fetch_rss(url, source, max_items=max_per_source)
        _log(f"📰 {source}: 抓到 {len(articles)} 則")
        us_articles.extend(articles)

    # 去重
    tw_before = len(tw_articles)
    tw_articles = deduplicate_news(tw_articles)
    _log(f"📰 台股新聞去重: {tw_before} → {len(tw_articles)} 則")

    us_before = len(us_articles)
    us_articles = deduplicate_news(us_articles)
    _log(f"📰 美股新聞去重: {us_before} → {len(us_articles)} 則")

    # 擷取內文摘要
    if fetch_content:
        for art in tw_articles + us_articles:
            content = extract_article_content(art["url"], max_chars=content_max_chars)
            art["summary"] = content
            status = f"{len(content)}字" if content else "僅標題"
            _log(
                f"  {'✅' if content else '⬜'} [{art['source']}] "
                f"{art['title'][:35]}... ({status})"
            )

    return tw_articles, us_articles
