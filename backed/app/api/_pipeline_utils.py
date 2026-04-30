"""
Pipeline 共用工具函数
提取自 pipeline_router.py 和 full_pipeline_router.py，避免重复定义。
"""
from __future__ import annotations

import re
from pathlib import Path


# 支持的平台列表（用于错误提示）
SUPPORTED_PLATFORMS = "抖音、Instagram、B站、TikTok、快手、X(Twitter)、YouTube"


def detect_platform(share_text: str) -> str:
    """
    检测分享文本中的平台类型。

    Returns:
        "douyin" | "bilibili" | "tiktok" | "kuaishou" | "instagram" | "x" | "youtube" | "unknown"
    """
    t = share_text.lower()
    if "douyin.com" in t or "v.douyin.com" in t:
        return "douyin"
    if "bilibili.com" in t or "b23.tv" in t:
        return "bilibili"
    if "tiktok.com" in t or "vm.tiktok" in t or "vt.tiktok" in t:
        return "tiktok"
    if "kuaishou.com" in t or "v.kuaishou.com" in t:
        return "kuaishou"
    if "instagram.com" in t or "instagr.am" in t:
        return "instagram"
    if "x.com" in t or "twitter.com" in t:
        return "x"
    if "youtube.com" in t or "youtu.be" in t:
        return "youtube"
    return "unknown"


def download_video_from_url(video_url: str, save_dir: Path, filename: str, platform: str = "") -> Path:
    """
    通用视频下载：从直链下载到本地文件。
    适用于所有非 YouTube 平台（extractor 只返回 video_url，不自带 download 方法）。
    """
    import requests
    from app.api.video_router import build_download_headers

    save_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', filename)[:80]
    if not safe_name.endswith(".mp4"):
        safe_name += ".mp4"
    dest = save_dir / safe_name

    headers = build_download_headers(platform, video_url)
    # 下载时不发 Range，避免触发 206 内容不匹配
    headers.pop("Range", None)

    with requests.get(video_url, headers=headers, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    return dest


def download_image_from_url(image_url: str, save_dir: Path, filename: str) -> Path:
    """通用图片下载：从直链下载到本地文件"""
    import requests

    save_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', filename)[:80]
    if not safe_name.lower().endswith((".jpg", ".jpeg", ".png")):
        safe_name += ".jpg"
    dest = save_dir / safe_name

    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Referer": "https://www.instagram.com/",
    }
    with requests.get(image_url, headers=headers, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    return dest
