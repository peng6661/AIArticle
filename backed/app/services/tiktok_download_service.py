"""
TikTok视频解析服务

注意：TikTok在中国大陆被封锁，需要VPN才能正常解析和下载
"""
import json
import re
import requests
from typing import Optional
from app.services.base import BaseExtractor


class TikTokExtractor(BaseExtractor):
    """TikTok视频解析器"""

    PLATFORM_NAME = "TikTok"
    TIKWM_API = "https://tikwm.com/api/"

    def __init__(self):
        self.session = requests.Session()
        self.timeout = 30

    def extract(self, url: str) -> Optional[dict]:
        """从TikTok URL提取视频信息"""
        normalized_url = self._normalize_url(url)
        if not normalized_url:
            return None

        # 使用 tikwm.com API
        try:
            resp = self.session.get(
                self.TIKWM_API,
                params={
                    "url": normalized_url,
                    "hd": "1",
                    "count": "12",
                    "cursor": "0",
                },
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://www.tikwm.com/",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
                timeout=self.timeout,
            )
            result = resp.json()
        except requests.exceptions.ConnectionError as e:
            print(f"[!] TikTok解析失败: 连接被重置，请检查网络环境（如需VPN请开启）")
            return None
        except requests.exceptions.Timeout:
            print(f"[!] TikTok解析超时，请稍后重试")
            return None
        except Exception as e:
            print(f"[!] TikTok解析失败: {e}")
            return None

        code = result.get("code", -1)
        if code != 0:
            msg = result.get("msg", "")
            print(f"[!] TikTok API返回错误: code={code}, msg={msg}")
            return None

        data = result.get("data", {})
        if not data:
            print(f"[!] TikTok API未返回数据")
            return None

        # 提取视频URL - 按优先级尝试多个字段
        video_url = ""

        # 打印所有可用的视频相关字段，便于调试
        print(f"[*] TikTok API返回数据 keys: {list(data.keys())}")

        # 优先尝试这些字段（包含完整视频流的）
        candidates = [
            ("hdplay", data.get("hdplay")),       # 高清视频
            ("wmplay", data.get("wmplay")),       # 带水印视频
            ("play", data.get("play")),            # 标准视频
            ("play_addr", data.get("play_addr")),  # 播放地址
            ("video_url", data.get("video_url")),  # 视频URL
            ("download_addr", data.get("download_addr")),  # 下载地址
        ]

        for name, url in candidates:
            if url and isinstance(url, str) and url.startswith("http"):
                video_url = url
                print(f"[*] 使用视频源: {name}")
                break

        # 检查play_addr
        if not video_url and isinstance(data.get("play_addr"), dict):
            play_addr = data.get("play_addr", {})
            for key in ["url_list", "url"]:
                if key in play_addr:
                    urls = play_addr[key] if isinstance(play_addr[key], list) else [play_addr[key]]
                    for u in urls:
                        if u and u.startswith("http") and "video" in u.lower():
                            video_url = u
                            print(f"[*] 从play_addr找到视频")
                            break
                    if video_url:
                        break

        # 检查download_addr
        if not video_url and isinstance(data.get("download_addr"), dict):
            dl_addr = data.get("download_addr", {})
            for key in ["url_list", "url"]:
                if key in dl_addr:
                    urls = dl_addr[key] if isinstance(dl_addr[key], list) else [dl_addr[key]]
                    for u in urls:
                        if u and u.startswith("http"):
                            video_url = u
                            print(f"[*] 从download_addr找到视频")
                            break
                    if video_url:
                        break

        if not video_url:
            print(f"[!] 未能获取到有效的视频URL，可能原因：")
            print(f"    1. TikTok在中国大陆需要VPN才能访问")
            print(f"    2. 该视频已被删除或设为私密")
            print(f"    3. 网络连接不稳定")
            return None

        # 封面
        cover = data.get("cover", "") or data.get("origin_cover", "")

        # 标题
        title = data.get("title", "")

        # 作者
        author_data = data.get("author", {}) or {}
        author = author_data.get("unique_id", "") or author_data.get("nickname", "")

        result_dict = {
            "title": title or f"TikTok_{author}",
            "video_url": video_url,
            "cover": cover,
        }

        return self.normalize_result(result_dict, self.PLATFORM_NAME)

    def _normalize_url(self, url: str) -> Optional[str]:
        """标准化TikTok URL"""
        url = url.strip()

        # 短链接
        m = re.search(r'(vm|vt)\.tiktok\.com/([A-Za-z0-9_-]+)', url)
        if m:
            try:
                resp = self.session.head(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                    timeout=10,
                    allow_redirects=True,
                )
                location = resp.headers.get("Location", "") or resp.url
                if "tiktok.com" in location:
                    return location
            except Exception:
                pass
            return None

        # 标准 URL
        m = re.search(r'tiktok\.com/@([A-Za-z0-9_.]+)/((?:video|photo)/(\d+))', url)
        if m:
            return url

        return None
