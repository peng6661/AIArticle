"""
视频解析服务统一入口
"""
import re
from typing import Optional
from app.services.base import BaseExtractor
from app.services.douyin_download_service import DouyinExtractor
from app.services.bilibili_download_service import BilibiliExtractor
from app.services.tiktok_download_service import TikTokExtractor
from app.services.kuaishou_download_service import KuaishouExtractor
from app.services.instagram_download_service import InstagramExtractor
from app.services.x_download_service import XVideoExtractor
from app.services.youtube_download_service import YouTubeExtractor


class VideoParser:
    """视频解析统一入口"""

    def __init__(self):
        self.extractors = {
            "douyin": DouyinExtractor(),
            "bilibili": BilibiliExtractor(),
            "tiktok": TikTokExtractor(),
            "kuaishou": KuaishouExtractor(),
            "instagram": InstagramExtractor(),
            "x": XVideoExtractor(),
            "youtube": YouTubeExtractor(),
        }

    def detect_platform(self, url: str) -> Optional[str]:
        """检测URL所属平台"""
        url_lower = url.lower()

        if "douyin.com" in url_lower or "v.douyin" in url_lower:
            return "douyin"
        elif "bilibili.com" in url_lower or "b23.tv" in url_lower:
            return "bilibili"
        elif "tiktok.com" in url_lower or "vm.tiktok" in url_lower or "vt.tiktok" in url_lower:
            return "tiktok"
        elif "kuaishou.com" in url_lower or "v.kuaishou" in url_lower:
            return "kuaishou"
        elif "instagram.com" in url_lower:
            return "instagram"
        elif "x.com" in url_lower or "twitter.com" in url_lower:
            return "x"
        elif "youtube.com" in url_lower or "youtu.be" in url_lower:
            return "youtube"

        return None

    def parse(self, url: str) -> Optional[dict]:
        """解析视频URL"""
        platform = self.detect_platform(url)
        if not platform:
            return None

        extractor = self.extractors.get(platform)
        if not extractor:
            return None

        try:
            result = extractor.extract(url)
            if result:
                result["platform"] = platform
                return result
        except Exception as e:
            print(f"解析{platform}失败: {e}")

        return None


# 全局实例
video_parser = VideoParser()
