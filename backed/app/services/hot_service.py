"""
热搜聚合服务
优先使用各平台官方 API，TopHub 仅作为兜底。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import threading
import time
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


NEWSNOW_HOME = "https://newsnow.busiyi.world/"
NEWSNOW_API = "https://newsnow.busiyi.world/api/s"
CACHE_TTL_SECONDS = 300


@dataclass
class HotEntry:
    rank: int
    title: str
    article_url: str
    score: str = ""
    source: str = ""


@dataclass
class HotBoard:
    id: str
    title: str
    source_url: str
    accent: str
    updated_at: str
    entries: list[HotEntry]


_cache_lock = threading.Lock()
_cache_data: dict[str, object] = {"expires_at": 0.0, "boards": []}


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
    })
    return session


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _format_compact_number(value: str) -> str:
    return _clean_text(value)


# ── 微博热搜 ────────────────────────────────────────────────────────────────

def _fetch_weibo(session: requests.Session) -> HotBoard:
    resp = session.get(
        "https://weibo.com/ajax/side/hotSearch",
        headers={"Accept": "application/json", "Referer": "https://weibo.com/"},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("data", {}).get("realtime", [])
    entries = []
    for i, item in enumerate(items):
        word = _clean_text(item.get("word", ""))
        if not word:
            continue
        num = item.get("num", 0)
        url = f"https://s.weibo.com/weibo?q=%23{requests.utils.quote(word)}%23"
        entries.append(HotEntry(
            rank=len(entries) + 1,
            title=word,
            article_url=url,
            score=f"{num} 讨论" if num else "",
            source="微博热搜",
        ))
        if len(entries) >= 30:
            break
    if not entries:
        raise ValueError("微博热搜: 无数据")
    return HotBoard(
        id="weibo", title="微博热搜", source_url="https://weibo.com/hot/search",
        accent="#f97316", updated_at=datetime.now().isoformat(), entries=entries,
    )


# ── 抖音热榜 ────────────────────────────────────────────────────────────────

def _fetch_douyin(session: requests.Session) -> HotBoard:
    resp = session.get(
        "https://www.douyin.com/aweme/v1/web/hot/search/list/",
        headers={"Accept": "application/json", "Referer": "https://www.douyin.com/"},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("data", {}).get("word_list", [])
    entries = []
    for item in items:
        word = _clean_text(item.get("word", ""))
        if not word:
            continue
        hot_value = item.get("hot_value", 0)
        url = f"https://www.douyin.com/search/{requests.utils.quote(word)}"
        entries.append(HotEntry(
            rank=len(entries) + 1,
            title=word,
            article_url=url,
            score=f"{hot_value}" if hot_value else "",
            source="抖音热榜",
        ))
        if len(entries) >= 30:
            break
    if not entries:
        raise ValueError("抖音热榜: 无数据")
    return HotBoard(
        id="douyin", title="抖音热榜", source_url="https://www.douyin.com/",
        accent="#111827", updated_at=datetime.now().isoformat(), entries=entries,
    )


# ── B站热榜 ──────────────────────────────────────────────────────────────────

def _fetch_bilibili(session: requests.Session) -> HotBoard:
    resp = session.get(
        "https://api.bilibili.com/x/web-interface/ranking/v2",
        params={"rid": 0, "type": "all"},
        headers={"Accept": "application/json", "Referer": "https://www.bilibili.com/"},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("data", {}).get("list", [])
    entries = []
    for item in items:
        title = _clean_text(item.get("title", ""))
        if not title:
            continue
        bvid = item.get("bvid", "")
        url = f"https://www.bilibili.com/video/{bvid}" if bvid else ""
        stat = item.get("stat", {})
        view = stat.get("view", 0)
        entries.append(HotEntry(
            rank=len(entries) + 1,
            title=title,
            article_url=url,
            score=f"{view} 播放" if view else "",
            source="B站热榜",
        ))
        if len(entries) >= 30:
            break
    if not entries:
        raise ValueError("B站热榜: 无数据")
    return HotBoard(
        id="bilibili", title="B站全站日榜", source_url="https://www.bilibili.com/v/popular/rank/all",
        accent="#ec4899", updated_at=datetime.now().isoformat(), entries=entries,
    )


# ── 百度热搜 ────────────────────────────────────────────────────────────────

def _fetch_baidu(session: requests.Session) -> HotBoard:
    resp = session.get(
        "https://top.baidu.com/board?tab=realtime",
        headers={"Accept": "text/html", "Referer": "https://top.baidu.com/"},
        timeout=15,
    )
    resp.raise_for_status()
    html = resp.text
    entries = []
    # 从 SSR 数据中提取
    m = re.search(r'<!--s-data:(.*?)-->', html, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            cards = data.get("data", {}).get("cards", [])
            if cards:
                for item in cards[0].get("content", []):
                    word = _clean_text(item.get("word", ""))
                    if not word:
                        continue
                    url = item.get("url", f"https://www.baidu.com/s?wd={requests.utils.quote(word)}")
                    desc = _clean_text(item.get("desc", ""))
                    entries.append(HotEntry(
                        rank=len(entries) + 1,
                        title=word,
                        article_url=url,
                        score=desc,
                        source="百度热搜",
                    ))
                    if len(entries) >= 30:
                        break
        except (json.JSONDecodeError, KeyError):
            pass
    if not entries:
        raise ValueError("百度热搜: 无数据")
    return HotBoard(
        id="baidu", title="百度热搜", source_url="https://top.baidu.com/board?tab=realtime",
        accent="#2563eb", updated_at=datetime.now().isoformat(), entries=entries,
    )


# ── 知乎热榜 (官方 API) ──────────────────────────────────────────────────────

def _fetch_zhihu(session: requests.Session) -> HotBoard:
    resp = session.get(
        "https://api.zhihu.com/topstory/hot-lists/total",
        params={"limit": 30},
        headers={"Accept": "application/json", "Referer": "https://www.zhihu.com/"},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("data", [])
    entries = []
    for item in items:
        target = item.get("target", {})
        title = _clean_text(target.get("title", ""))
        if not title:
            continue
        url = target.get("url", "")
        if url and url.startswith("https://api.zhihu.com"):
            m = re.search(r"/(\d+)$", url)
            url = f"https://www.zhihu.com/question/{m.group(1)}" if m else ""
        if not url:
            qid = target.get("id", "")
            url = f"https://www.zhihu.com/question/{qid}" if qid else ""
        detail = _clean_text(target.get("excerpt", ""))
        entries.append(HotEntry(
            rank=len(entries) + 1,
            title=title,
            article_url=url,
            score=detail,
            source="知乎热榜",
        ))
        if len(entries) >= 30:
            break
    if not entries:
        raise ValueError("知乎热榜: 无数据")
    return HotBoard(
        id="zhihu", title="知乎热榜", source_url="https://www.zhihu.com/hot",
        accent="#3b82f6", updated_at=datetime.now().isoformat(), entries=entries,
    )


# ── 微信热文 (TopHub 主页提取，绕过节点页 403) ─────────────────────────────────

def _fetch_wechat(session: requests.Session) -> HotBoard:
    """从 TopHub 主页提取微信热文数据（节点页有验证码保护，主页可正常访问）。"""
    resp = session.get("https://tophub.today/", timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    # 在主页的 cc-cd 卡片中查找"微信"板块
    wechat_card = None
    for card in soup.select("div.cc-cd"):
        title_el = card.select_one(".cc-cd-lb, .cc-cd-sb")
        if title_el and "微信" in title_el.get_text(strip=True):
            wechat_card = card
            break
    if not wechat_card:
        raise ValueError("微信热文: 主页未找到微信板块")

    entries = []
    for a in wechat_card.select("a[href]"):
        href = a.get("href", "").strip()
        if not href or "tophub.today" in href:
            continue
        text = a.get_text(strip=True)
        m = re.match(r"^(\d+)(.+)", text)
        if not m:
            continue
        rank = int(m.group(1))
        title = _clean_text(m.group(2))
        # 去掉末尾的热度分数（如 "10.0"）
        title = re.sub(r"\s*\d+\.\d+$", "", title).strip()
        if not title:
            continue
        entries.append(HotEntry(
            rank=rank, title=title, article_url=href,
            source="微信热文",
        ))
        if len(entries) >= 30:
            break

    if not entries:
        raise ValueError("微信热文: 无数据")
    return HotBoard(
        id="wechat", title="微信24h热文", source_url="https://tophub.today/n/WnBe01o371",
        accent="#22c55e", updated_at=datetime.now().isoformat(), entries=entries,
    )


# ── GitHub 热榜 (NewsNow) ──────────────────────────────────────────────────

def _fetch_github(session: requests.Session) -> HotBoard:
    return _fetch_newsnow(session, "github", "GitHub 热榜", "#8b5cf6")


# ── 牛客热榜 (NewsNow) ──────────────────────────────────────────────────────

def _fetch_nowcoder(session: requests.Session) -> HotBoard:
    return _fetch_newsnow(session, "nowcoder", "牛客热榜", "#f14d42")


def _fetch_newsnow(session: requests.Session, source_id: str, title: str, accent: str) -> HotBoard:
    """从 NewsNow API 获取榜单。"""
    resp = session.get(
        NEWSNOW_API, params={"id": source_id}, timeout=20,
        headers={"Accept": "application/json", "Referer": NEWSNOW_HOME, "Origin": NEWSNOW_HOME.rstrip("/")},
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    entries = []
    for item in items:
        entry_title = _clean_text(item.get("title", ""))
        url = (item.get("url") or "").strip()
        if not entry_title or not url:
            continue
        extra = item.get("extra") or {}
        score = _clean_text(extra.get("info", "")) if isinstance(extra, dict) else ""
        entries.append(HotEntry(
            rank=len(entries) + 1, title=entry_title,
            article_url=url, score=score, source=title,
        ))
        if len(entries) >= 30:
            break
    if not entries:
        raise ValueError(f"NewsNow {source_id}: 无数据")
    return HotBoard(
        id=f"newsnow_{source_id}", title=title,
        source_url=f"{NEWSNOW_HOME}?id={source_id}",
        accent=accent, updated_at=datetime.now().isoformat(), entries=entries,
    )


# ── AI HOT 日报 ─────────────────────────────────────────────────────────────

def _fetch_aihot_daily(session: requests.Session) -> HotBoard:
    """从 aihot.virxact.com/daily 爬取当日 AI 日报文章。"""
    resp = session.get(
        "https://aihot.virxact.com/daily",
        headers={"Accept": "text/html"},
        timeout=20,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    entries = []
    for article in soup.select("article.daily-article"):
        title_el = article.select_one(".daily-article-title a")
        if not title_el:
            continue
        title = _clean_text(title_el.get_text())
        url = (title_el.get("href") or "").strip()
        if not title or not url:
            continue

        # 信源标签 + 信源名称
        source_parts = []
        for tag_el in article.select(".daily-article-source .role-tag"):
            source_parts.append(_clean_text(tag_el.get_text()))
        source_name_el = article.select_one(".daily-article-source span:last-child")
        if source_name_el:
            source_parts.append(_clean_text(source_name_el.get_text()))
        source = " · ".join(source_parts) if source_parts else ""

        # 摘要（取前 60 字作为 score 字段展示）
        summary_el = article.select_one(".daily-article-summary")
        summary = _clean_text(summary_el.get_text())[:60] if summary_el else ""

        entries.append(HotEntry(
            rank=len(entries) + 1, title=title, article_url=url,
            score=summary, source=source,
        ))
        if len(entries) >= 30:
            break

    if not entries:
        raise ValueError("AI HOT 日报: 无数据")
    return HotBoard(
        id="aihot_daily", title="AI HOT 日报",
        source_url="https://aihot.virxact.com/daily",
        accent="#f59e0b", updated_at=datetime.now().isoformat(), entries=entries,
    )


# ── AI HOT 精选 ─────────────────────────────────────────────────────────────

def _fetch_aihot_feed(session: requests.Session) -> HotBoard:
    """从 aihot.virxact.com/feed.xml 爬取 AI 精选文章。"""
    import xml.etree.ElementTree as ET

    resp = session.get(
        "https://aihot.virxact.com/feed.xml",
        headers={"Accept": "application/rss+xml, application/xml, text/xml"},
        timeout=20,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.text)

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    channel = root.find("channel")
    if channel is None:
        raise ValueError("AI HOT 精选: RSS 格式异常")

    entries = []
    for item in channel.findall("item"):
        title = _clean_text(item.findtext("title", ""))
        url = (item.findtext("link") or "").strip()
        if not title or not url:
            continue
        description = _clean_text(item.findtext("description", ""))[:60]
        author = _clean_text(item.findtext("author", ""))
        # author 格式通常是 "noreply@... (来源名)"，提取括号内来源
        m = re.search(r"\(([^)]+)\)", author)
        source = m.group(1) if m else author

        entries.append(HotEntry(
            rank=len(entries) + 1, title=title, article_url=url,
            score=description, source=source,
        ))
        if len(entries) >= 30:
            break

    if not entries:
        raise ValueError("AI HOT 精选: 无数据")
    return HotBoard(
        id="aihot_feed", title="AI HOT 精选",
        source_url="https://aihot.virxact.com/feed.xml",
        accent="#06b6d4", updated_at=datetime.now().isoformat(), entries=entries,
    )





def _fetch_v2ex(session: requests.Session) -> HotBoard:
    resp = session.get(
        "https://www.v2ex.com/",
        headers={"Accept": "text/html", "Referer": "https://www.v2ex.com/"},
        timeout=20,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    entries: list[HotEntry] = []
    top_box = None
    for box in soup.select("div.box"):
        header = _clean_text(box.get_text(" ", strip=True))
        if "Today Top 10" in header:
            top_box = box
            break

    if top_box:
        for link in top_box.select("a[href^='/t/']"):
            title = _clean_text(link.get_text())
            href = (link.get("href") or "").strip()
            if not title or not href:
                continue
            entries.append(HotEntry(
                rank=len(entries) + 1,
                title=title,
                article_url=urljoin("https://www.v2ex.com", href),
                source="Today Top 10",
            ))
            if len(entries) >= 10:
                break

    if not entries:
        for item in soup.select("div.cell.item"):
            title_el = item.select_one("span.item_title a[href^='/t/']")
            if not title_el:
                continue
            title = _clean_text(title_el.get_text())
            href = (title_el.get("href") or "").strip()
            if not title or not href:
                continue
            meta = item.select_one("span.topic_info")
            score = _clean_text(meta.get_text(" ", strip=True)) if meta else ""
            entries.append(HotEntry(
                rank=len(entries) + 1,
                title=title,
                article_url=urljoin("https://www.v2ex.com", href),
                score=score,
                source="V2EX",
            ))
            if len(entries) >= 30:
                break

    if not entries:
        raise ValueError("V2EX: 鏃犳暟鎹?")

    return HotBoard(
        id="v2ex", title="V2EX 帖子",
        source_url="https://www.v2ex.com/",
        accent="#f59e0b", updated_at=datetime.now().isoformat(), entries=entries,
    )


def _serialize_board(board: HotBoard) -> dict:
    payload = asdict(board)
    payload["entries"] = [asdict(entry) for entry in board.entries]
    return payload


# ── 榜单注册表 ──────────────────────────────────────────────────────────────

BOARD_FETCHERS = [
    {"id": "v2ex", "title": "V2EX 帖子", "fetch": _fetch_v2ex},
    {"id": "weibo",    "title": "微博热搜",     "fetch": _fetch_weibo},
    {"id": "douyin",   "title": "抖音热榜",     "fetch": _fetch_douyin},
    {"id": "bilibili", "title": "B站热榜",      "fetch": _fetch_bilibili},
    {"id": "baidu",    "title": "百度热搜",     "fetch": _fetch_baidu},
    {"id": "zhihu",    "title": "知乎热榜",     "fetch": _fetch_zhihu},
    {"id": "wechat",   "title": "微信热文",     "fetch": _fetch_wechat},
    {"id": "github",   "title": "GitHub 热榜",  "fetch": _fetch_github},
    {"id": "juejin",   "title": "稀土掘金",     "fetch": lambda s: _fetch_newsnow(s, "juejin", "稀土掘金", "#1e80ff")},
    {"id": "nowcoder",    "title": "牛客热榜",     "fetch": _fetch_nowcoder},
    {"id": "aihot_daily", "title": "AI HOT 日报",  "fetch": _fetch_aihot_daily},
    {"id": "aihot_feed",  "title": "AI HOT 精选",  "fetch": _fetch_aihot_feed},
]


def fetch_hot_boards(force_refresh: bool = False) -> tuple[list[dict], list[str]]:
    """
    获取所有热榜数据。

    Returns:
        (boards, errors) — 成功的榜单列表 + 失败的错误信息列表
    """
    now = time.time()
    with _cache_lock:
        if not force_refresh and _cache_data["boards"] and now < float(_cache_data["expires_at"]):
            return list(_cache_data["boards"]), []

    session = _build_session()
    boards: list[dict] = []
    errors: list[str] = []

    for source in BOARD_FETCHERS:
        try:
            board = source["fetch"](session)
            boards.append(_serialize_board(board))
        except Exception as exc:
            errors.append(f"{source['id']}: {exc}")

    if not boards:
        raise RuntimeError("所有热榜抓取均失败: " + "; ".join(errors))

    with _cache_lock:
        _cache_data["boards"] = boards
        _cache_data["expires_at"] = now + CACHE_TTL_SECONDS

    return boards, errors
