"""
解析服务基类
"""
from abc import ABC, abstractmethod
from typing import Optional


class BaseExtractor(ABC):
    """视频解析器基类"""

    @abstractmethod
    def extract(self, url: str) -> Optional[dict]:
        """
        从URL提取视频信息

        Args:
            url: 视频链接

        Returns:
            包含视频信息的字典，包括:
            - title: 标题
            - video_url: 视频地址
            - cover_url: 封面图
            - platform: 平台名称
        """
        pass

    def normalize_result(self, result: dict, platform: str) -> dict:
        """标准化返回结果"""
        video_url = result.get("video_url") or result.get("url", "")
        cover_url = result.get("cover_url") or result.get("cover") or result.get("thumbnail", "")
        images = result.get("images", [])

        # 自动判断媒体类型
        if video_url:
            media_type = "video"
        else:
            media_type = "image"

        return {
            "title": result.get("title", ""),
            "video_url": video_url,
            "cover_url": cover_url,
            "image_url": "",  # 兼容旧字段
            "platform": platform,
            "media_type": media_type,
            "images": images,
            "image_count": len(images) if images else (1 if media_type == "image" else 0),
        }
