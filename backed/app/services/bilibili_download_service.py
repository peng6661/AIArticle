"""
B站视频解析服务
"""
import json
import re
import requests
from typing import Optional
from app.services.base import BaseExtractor


class BilibiliExtractor(BaseExtractor):
    """B站视频解析器"""

    PLATFORM_NAME = "哔哩哔哩"

    QUALITY_MAP = {
        127: "8K", 126: "杜比视界", 125: "HDR",
        120: "4K", 116: "1080P60", 112: "1080P+",
        80: "1080P", 64: "720P", 32: "480P", 16: "360P",
    }

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.bilibili.com/",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.timeout = 15

    def extract(self, share_text: str) -> Optional[dict]:
        """从B站分享文本提取视频信息"""
        bvid = self._parse_bvid(share_text)
        if not bvid:
            return None

        meta = self._get_video_meta(bvid)
        if not meta:
            return None

        title = meta.get("title", "")
        cid = meta.get("cid", 0)

        video_data = self._get_download_url(bvid, cid)
        if not video_data:
            return None

        video_data["title"] = title
        video_data["cover"] = meta.get("pic", "")

        return self.normalize_result(video_data, self.PLATFORM_NAME)

    def _parse_bvid(self, text: str) -> Optional[str]:
        m = re.search(r'(BV[A-Za-z0-9]{10,})', text)
        return m.group(1) if m else None

    def _get_video_meta(self, bvid: str) -> Optional[dict]:
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        try:
            r = self.session.get(url, timeout=self.timeout)
            d = r.json().get("data", {})
            if d:
                return {
                    "title": d.get("title", ""),
                    "aid": d.get("aid"),
                    "cid": d.get("cid"),
                    "pic": d.get("pic", ""),
                }
        except Exception:
            pass
        return None

    def _get_download_url(self, bvid: str, cid: int) -> Optional[dict]:
        api_url = f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&qn=80&fnval=0&fourk=1"
        headers = {**self.headers, "Referer": f"https://www.bilibili.com/video/{bvid}/"}

        try:
            resp = self.session.get(api_url, headers=headers, timeout=self.timeout)
            result = resp.json()
        except Exception:
            return None

        if result.get("code") != 0:
            return None

        data = result.get("data", {})

        # MP4 直链
        durl = data.get("durl", [])
        if durl:
            return {
                "video_url": durl[0].get("url", ""),
                "cover": ""
            }

        # DASH 格式
        dash = data.get("dash", {})
        if dash:
            videos = dash.get("video", [])
            audios = dash.get("audio", [])
            if videos and audios:
                return {
                    "video_url": videos[0].get("baseUrl", ""),
                    "cover": ""
                }

        return None
