"""
多平台热点视频搜索服务
支持抖音、B站、YouTube、TikTok、快手、Instagram、X 并发检索
"""
from __future__ import annotations

import asyncio
import json
import math
import subprocess
import re
from dataclasses import dataclass, asdict, field
from typing import Optional

import requests


@dataclass
class VideoSearchResult:
    title: str
    url: str
    cover_url: str = ""
    platform: str = ""
    author: str = ""
    play_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    duration: int = 0
    publish_time: str = ""
    heat_score: float = 0.0
    description: str = ""


def _clean_html(text: str) -> str:
    """去除 HTML 标签"""
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _calc_heat_score(
    play: int = 0, like: int = 0, comment: int = 0, share: int = 0
) -> float:
    """
    计算标准化热度分（0-100）。
    使用对数归一化，权重：播放 0.4 + 点赞 0.3 + 评论 0.2 + 分享 0.1
    """
    def _norm(v: int) -> float:
        if v <= 0:
            return 0.0
        return min(math.log10(v + 1) / 8.0, 1.0)  # 10^8 ≈ 1亿 → 1.0

    score = (
        0.4 * _norm(play)
        + 0.3 * _norm(like)
        + 0.2 * _norm(comment)
        + 0.1 * _norm(share)
    )
    return round(score * 100, 1)


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


# ── B站搜索 ──────────────────────────────────────────────────────────────────

def search_bilibili_sync(keyword: str, limit: int = 10) -> list[VideoSearchResult]:
    session = _build_session()
    # B站搜索 API 需要先访问主页获取 cookie，否则返回 412
    session.get("https://www.bilibili.com/", timeout=10)
    resp = session.get(
        "https://api.bilibili.com/x/web-interface/search/type",
        params={"search_type": "video", "keyword": keyword, "page": 1, "pagesize": limit},
        headers={"Referer": "https://www.bilibili.com/"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise ValueError(f"B站 API 错误: {data.get('message', '未知')}")

    results = []
    for item in data.get("data", {}).get("result", []):
        title = _clean_html(item.get("title", ""))
        bvid = item.get("bvid", "")
        url = f"https://www.bilibili.com/video/{bvid}" if bvid else ""
        pic = item.get("pic", "")
        if pic and not pic.startswith("http"):
            pic = "https:" + pic
        play = item.get("play", 0)
        like = item.get("like", 0)
        review = item.get("review", 0)  # 评论数
        favorites = item.get("favorites", 0)
        duration_str = item.get("duration", "")
        # 解析时长 "MM:SS" 或 "HH:MM:SS"
        duration = 0
        if duration_str:
            parts = duration_str.split(":")
            try:
                if len(parts) == 3:
                    duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                elif len(parts) == 2:
                    duration = int(parts[0]) * 60 + int(parts[1])
            except ValueError:
                pass

        results.append(VideoSearchResult(
            title=title,
            url=url,
            cover_url=pic,
            platform="bilibili",
            author=item.get("author", ""),
            play_count=play,
            like_count=like,
            comment_count=review,
            duration=duration,
            publish_time=item.get("pubdate_str", ""),
            heat_score=_calc_heat_score(play, like, review),
            description=_clean_html(item.get("description", ""))[:200],
        ))
    return results[:limit]


# ── YouTube 搜索（yt-dlp）────────────────────────────────────────────────────

def search_youtube_sync(keyword: str, limit: int = 10) -> list[VideoSearchResult]:
    cmd = [
        "yt-dlp", "--flat-playlist", "--dump-json",
        "--playlist-items", f"1:{limit}",
        f"ytsearch{limit}:{keyword}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise ValueError(f"yt-dlp 搜索失败: {proc.stderr[:200]}")

    results = []
    for line in proc.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue

        video_id = item.get("id", "")
        url = item.get("url") or item.get("webpage_url") or ""
        if not url and video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
        title = item.get("title", "")
        thumbnail = item.get("thumbnail") or ""
        # 尝试从 thumbnails 列表获取
        if not thumbnail and item.get("thumbnails"):
            thumbs = item["thumbnails"]
            if thumbs:
                thumbnail = thumbs[-1].get("url", "")
        view_count = item.get("view_count") or 0
        like_count = item.get("like_count") or 0
        comment_count = item.get("comment_count") or 0
        duration = int(item.get("duration") or 0)
        upload_date = item.get("upload_date") or ""
        channel = item.get("channel") or item.get("uploader") or ""
        desc = item.get("description") or ""

        results.append(VideoSearchResult(
            title=title,
            url=url,
            cover_url=thumbnail,
            platform="youtube",
            author=channel,
            play_count=view_count,
            like_count=like_count,
            comment_count=comment_count,
            duration=duration,
            publish_time=upload_date,
            heat_score=_calc_heat_score(view_count, like_count, comment_count),
            description=desc[:200],
        ))
    return results[:limit]


# ── 抖音搜索 ─────────────────────────────────────────────────────────────────

def search_douyin_sync(keyword: str, limit: int = 10) -> list[VideoSearchResult]:
    """
    通过 Playwright 加载抖音搜索页面，拦截 API 响应获取视频数据。
    抖音搜索 API 需要 JS 生成的 a_bogus 签名，必须用浏览器执行。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _search_douyin_api_fallback(keyword, limit)

    from datetime import datetime
    from urllib.parse import quote

    captured_data = []

    def handle_response(response):
        try:
            url = response.url
            if "/aweme/v1/web/search/item/" in url and response.status == 200:
                body = response.json()
                if body.get("data"):
                    captured_data.extend(body["data"])
                elif body.get("aweme_list"):
                    captured_data.extend(body["aweme_list"])
        except Exception:
            pass

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                channel="chrome",
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
            )
            page = context.new_page()
            page.on("response", handle_response)

            search_url = f"https://www.douyin.com/search/{quote(keyword)}?type=video"
            page.goto(search_url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            # 如果 API 拦截没有数据，尝试从页面 DOM 提取
            if not captured_data:
                captured_data = _extract_douyin_from_dom(page)

            browser.close()
    except Exception:
        return _search_douyin_api_fallback(keyword, limit)

    results = []
    for aweme in captured_data[:limit]:
        aweme = aweme.get("aweme_info", aweme)
        desc = aweme.get("desc", "")
        if not desc:
            continue
        statistics = aweme.get("statistics", {})
        play_count = statistics.get("play_count", 0) or statistics.get("vv_count", 0)
        digg_count = statistics.get("digg_count", 0)
        comment_count = statistics.get("comment_count", 0)
        share_count = statistics.get("share_count", 0)
        author = aweme.get("author", {}).get("nickname", "")
        aweme_id = aweme.get("aweme_id", "")
        url = f"https://www.douyin.com/video/{aweme_id}" if aweme_id else ""
        cover = ""
        video_info = aweme.get("video", {})
        cover_obj = video_info.get("cover", {}) or video_info.get("origin_cover", {})
        if cover_obj:
            url_list = cover_obj.get("url_list", [])
            if url_list:
                cover = url_list[0]
        dur = video_info.get("duration", 0)
        duration = int(dur / 1000) if dur > 1000 else int(dur)
        create_time = aweme.get("create_time", "")
        if create_time:
            try:
                create_time = datetime.fromtimestamp(int(create_time)).strftime("%Y-%m-%d")
            except (ValueError, OSError):
                create_time = ""

        results.append(VideoSearchResult(
            title=desc, url=url, cover_url=cover, platform="douyin",
            author=author, play_count=play_count, like_count=digg_count,
            comment_count=comment_count, share_count=share_count,
            duration=duration, publish_time=create_time,
            heat_score=_calc_heat_score(play_count, digg_count, comment_count, share_count),
            description=desc[:200],
        ))
    return results[:limit]


def _extract_douyin_from_dom(page) -> list[dict]:
    """从抖音搜索页 DOM 中提取视频卡片数据"""
    try:
        items = page.query_selector_all('[class*="search-result"] a[href*="/video/"], [class*="video-card"], li[class*="result"] a[href*="/video/"]')
        results = []
        for item in items:
            href = item.get_attribute("href") or ""
            aweme_id = ""
            m = re.search(r'/video/(\d+)', href)
            if m:
                aweme_id = m.group(1)
            title_el = item.query_selector('[class*="title"], [class*="desc"], p, h3')
            title = title_el.inner_text().strip() if title_el else ""
            img_el = item.query_selector("img")
            cover = img_el.get_attribute("src") if img_el else ""
            if aweme_id or title:
                results.append({
                    "aweme_id": aweme_id,
                    "desc": title,
                    "video": {"cover": {"url_list": [cover] if cover else []}},
                    "statistics": {},
                    "author": {},
                })
        return results
    except Exception:
        return []


def _search_douyin_api_fallback(keyword: str, limit: int) -> list[VideoSearchResult]:
    """降级：直接请求抖音 API（通常因缺少签名返回空结果）"""
    from datetime import datetime
    session = _build_session()
    session.get("https://www.douyin.com/", timeout=15)
    try:
        resp = session.get(
            "https://www.douyin.com/aweme/v1/web/search/item/",
            params={
                "keyword": keyword,
                "search_channel": "aweme_video_web",
                "count": limit,
                "search_source": "hot_search_board",
                "query_correct_type": 1,
                "is_filter_search": 0,
                "from_group_id": "",
                "offset": 0,
            },
            headers={"Accept": "application/json", "Referer": "https://www.douyin.com/"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data") or data.get("aweme_list") or []
        if not items:
            return []
        results = []
        for item in items:
            aweme = item.get("aweme_info", item)
            desc = aweme.get("desc", "")
            if not desc:
                continue
            statistics = aweme.get("statistics", {})
            play_count = statistics.get("play_count", 0)
            digg_count = statistics.get("digg_count", 0)
            comment_count = statistics.get("comment_count", 0)
            share_count = statistics.get("share_count", 0)
            author = aweme.get("author", {}).get("nickname", "")
            aweme_id = aweme.get("aweme_id", "")
            url = f"https://www.douyin.com/video/{aweme_id}" if aweme_id else ""
            cover = aweme.get("video", {}).get("cover", {}).get("url_list", [""])[0]
            duration = int(aweme.get("video", {}).get("duration", 0) / 1000)
            create_time = aweme.get("create_time", "")
            if create_time:
                try:
                    create_time = datetime.fromtimestamp(int(create_time)).strftime("%Y-%m-%d")
                except (ValueError, OSError):
                    create_time = ""
            results.append(VideoSearchResult(
                title=desc, url=url, cover_url=cover, platform="douyin",
                author=author, play_count=play_count, like_count=digg_count,
                comment_count=comment_count, share_count=share_count,
                duration=duration, publish_time=create_time,
                heat_score=_calc_heat_score(play_count, digg_count, comment_count, share_count),
                description=desc[:200],
            ))
        return results[:limit]
    except Exception:
        return []


# ── TikTok 搜索（yt-dlp）────────────────────────────────────────────────────

def search_tiktok_sync(keyword: str, limit: int = 10) -> list[VideoSearchResult]:
    """通过 yt-dlp 搜索 TikTok 视频"""
    search_url = f"https://www.tiktok.com/search/video?keyword={keyword}"
    cmd = [
        "yt-dlp", "--flat-playlist", "--dump-json",
        "--playlist-items", f"1:{limit}",
        search_url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise ValueError(f"TikTok 搜索失败: {proc.stderr[:200]}")

    results = []
    for line in proc.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue

        video_id = item.get("id", "")
        url = item.get("url") or item.get("webpage_url") or ""
        title = item.get("title") or item.get("description", "")
        thumbnail = item.get("thumbnail") or ""
        view_count = item.get("view_count") or 0
        like_count = item.get("like_count") or 0
        comment_count = item.get("comment_count") or 0
        share_count = item.get("repost_count") or 0
        duration = int(item.get("duration") or 0)
        uploader = item.get("uploader") or item.get("creator") or ""

        results.append(VideoSearchResult(
            title=title,
            url=url,
            cover_url=thumbnail,
            platform="tiktok",
            author=uploader,
            play_count=view_count,
            like_count=like_count,
            comment_count=comment_count,
            share_count=share_count,
            duration=duration,
            heat_score=_calc_heat_score(view_count, like_count, comment_count, share_count),
            description=title[:200],
        ))
    return results[:limit]


# ── 快手搜索 ─────────────────────────────────────────────────────────────────

def search_kuaishou_sync(keyword: str, limit: int = 10) -> list[VideoSearchResult]:
    """通过快手 GraphQL API 搜索视频"""
    session = _build_session()
    resp = session.post(
        "https://www.kuaishou.com/graphql",
        json={
            "operationName": "visionSearchPhoto",
            "variables": {
                "keyword": keyword,
                "pcursor": "",
                "page": "search",
                "searchSessionId": "",
            },
            "query": """
            query visionSearchPhoto($keyword: String, $pcursor: String, $page: String, $searchSessionId: String) {
                visionSearchPhoto(keyword: $keyword, pcursor: $pcursor, page: $page, searchSessionId: $searchSessionId) {
                    result
                    llsid
                    webPageArea
                    feeds {
                        type
                        photo {
                            id
                            caption
                            coverUrl
                            photoUrl
                            duration
                            viewCount
                            likeCount
                            commentCount
                            timestamp
                            author {
                                name
                            }
                        }
                    }
                }
            }
            """,
        },
        headers={
            "Accept": "application/json",
            "Referer": "https://www.kuaishou.com/",
            "Origin": "https://www.kuaishou.com",
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    feeds = data.get("data", {}).get("visionSearchPhoto", {}).get("feeds", [])

    results = []
    for feed in feeds:
        photo = feed.get("photo", {})
        if not photo:
            continue
        photo_id = photo.get("id", "")
        caption = photo.get("caption", "")
        cover_url = photo.get("coverUrl", "")
        view_count = photo.get("viewCount", 0)
        like_count = photo.get("likeCount", 0)
        comment_count = photo.get("commentCount", 0)
        duration = photo.get("duration", 0)
        author_info = photo.get("author", {})
        author = author_info.get("name", "")
        url = f"https://www.kuaishou.com/short-video/{photo_id}" if photo_id else ""
        timestamp = photo.get("timestamp", 0)
        publish_time = ""
        if timestamp:
            from datetime import datetime
            try:
                publish_time = datetime.fromtimestamp(timestamp / 1000).strftime("%Y-%m-%d")
            except (ValueError, OSError):
                pass

        results.append(VideoSearchResult(
            title=caption,
            url=url,
            cover_url=cover_url,
            platform="kuaishou",
            author=author,
            play_count=view_count,
            like_count=like_count,
            comment_count=comment_count,
            duration=int(duration / 1000) if duration > 1000 else duration,
            publish_time=publish_time,
            heat_score=_calc_heat_score(view_count, like_count, comment_count),
            description=caption[:200],
        ))
    return results[:limit]


# ── Instagram 搜索（yt-dlp）──────────────────────────────────────────────────

def search_instagram_sync(keyword: str, limit: int = 10) -> list[VideoSearchResult]:
    """通过 yt-dlp 搜索 Instagram Reels（按关键词标签）"""
    tag = keyword.replace(" ", "").replace("#", "")
    search_url = f"https://www.instagram.com/explore/tags/{tag}/"
    cmd = [
        "yt-dlp", "--flat-playlist", "--dump-json",
        "--playlist-items", f"1:{limit}",
        search_url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise ValueError(f"Instagram 搜索失败: {proc.stderr[:200]}")

    results = []
    for line in proc.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue

        url = item.get("url") or item.get("webpage_url") or ""
        title = item.get("title") or item.get("description", "")
        thumbnail = item.get("thumbnail") or ""
        view_count = item.get("view_count") or 0
        like_count = item.get("like_count") or 0
        comment_count = item.get("comment_count") or 0
        duration = int(item.get("duration") or 0)
        uploader = item.get("uploader") or ""

        results.append(VideoSearchResult(
            title=title,
            url=url,
            cover_url=thumbnail,
            platform="instagram",
            author=uploader,
            play_count=view_count,
            like_count=like_count,
            comment_count=comment_count,
            duration=duration,
            heat_score=_calc_heat_score(view_count, like_count, comment_count),
            description=title[:200],
        ))
    return results[:limit]


# ── X (Twitter) 搜索（yt-dlp）───────────────────────────────────────────────

def search_x_sync(keyword: str, limit: int = 10) -> list[VideoSearchResult]:
    """通过 yt-dlp 搜索 X/Twitter 视频"""
    search_url = f"https://x.com/search?q={keyword}&f=video"
    cmd = [
        "yt-dlp", "--flat-playlist", "--dump-json",
        "--playlist-items", f"1:{limit}",
        search_url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise ValueError(f"X 搜索失败: {proc.stderr[:200]}")

    results = []
    for line in proc.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue

        url = item.get("url") or item.get("webpage_url") or ""
        title = item.get("title") or item.get("description", "")
        thumbnail = item.get("thumbnail") or ""
        view_count = item.get("view_count") or 0
        like_count = item.get("like_count") or 0
        comment_count = item.get("comment_count") or 0
        repost_count = item.get("repost_count") or 0
        duration = int(item.get("duration") or 0)
        uploader = item.get("uploader") or ""

        results.append(VideoSearchResult(
            title=title,
            url=url,
            cover_url=thumbnail,
            platform="x",
            author=uploader,
            play_count=view_count,
            like_count=like_count,
            comment_count=comment_count,
            share_count=repost_count,
            duration=duration,
            heat_score=_calc_heat_score(view_count, like_count, comment_count, repost_count),
            description=title[:200],
        ))
    return results[:limit]


# ── 平台注册表 ───────────────────────────────────────────────────────────────

PLATFORM_FETCHERS: dict[str, tuple[str, callable]] = {
    "bilibili":  ("B站",     search_bilibili_sync),
    "youtube":   ("YouTube", search_youtube_sync),
    "kuaishou":  ("快手",    search_kuaishou_sync),
    "instagram": ("Instagram", search_instagram_sync),
}

ALL_PLATFORMS = list(PLATFORM_FETCHERS.keys())


async def search_platform(
    platform_id: str, keyword: str, limit: int = 10
) -> tuple[str, list[VideoSearchResult], Optional[str]]:
    """
    异步搜索单个平台。
    Returns: (platform_id, results, error_message_or_None)
    """
    info = PLATFORM_FETCHERS.get(platform_id)
    if not info:
        return platform_id, [], f"未知平台: {platform_id}"

    name, func = info
    try:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, func, keyword, limit)
        # 按热度分排序
        results.sort(key=lambda r: r.heat_score, reverse=True)
        return platform_id, results, None
    except Exception as exc:
        return platform_id, [], f"{name}: {exc}"


async def search_all(
    keyword: str,
    platforms: Optional[list[str]] = None,
    limit: int = 10,
) -> tuple[dict[str, list[dict]], list[str]]:
    """
    并发搜索所有指定平台。

    Returns:
        (results_dict, errors_list)
        results_dict: { "bilibili": [VideoSearchResult...], ... }
        errors_list: ["平台名: 错误信息", ...]
    """
    if not platforms:
        platforms = ALL_PLATFORMS

    tasks = [search_platform(pid, keyword, limit) for pid in platforms]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    results: dict[str, list[dict]] = {}
    errors: list[str] = []

    for item in gathered:
        if isinstance(item, Exception):
            errors.append(str(item))
            continue
        pid, vids, err = item
        if err:
            errors.append(err)
        if vids:
            results[pid] = [asdict(v) for v in vids]

    return results, errors
