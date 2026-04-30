"""
快手视频解析服务
"""
import json
import re
import requests
from typing import Optional
from app.services.base import BaseExtractor


class KuaishouExtractor(BaseExtractor):
    """快手视频解析器"""

    PLATFORM_NAME = "快手"

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 Kwai/12.3.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://www.kuaishou.com/',
        }
        self.timeout = 10

    def extract(self, share_text: str) -> Optional[dict]:
        """从快手分享文本提取视频信息"""
        # 从video标签直接提取
        video_data = self._extract_from_video_tag(share_text)
        if video_data:
            return self.normalize_result(video_data, self.PLATFORM_NAME)

        # 从短链接提取
        url_match = re.search(r'https://v\.kuaishou\.com/[A-Za-z0-9_-]+/?', share_text)
        if not url_match:
            return None

        short_url = url_match.group(0)

        try:
            video_data = self._try_mobile_access(short_url)
            if video_data:
                return self.normalize_result(video_data, self.PLATFORM_NAME)
        except Exception as e:
            print(f"快手解析失败: {e}")

        return None

    def _extract_from_video_tag(self, text: str) -> Optional[dict]:
        pattern = r'<video[^>]+src=["\']([^"\']+)["\']'
        match = re.search(pattern, text, re.I | re.S)
        if match:
            video_url = match.group(1).replace('&amp;', '&')
            title_match = re.search(r'["""]([^"""]{5,50})["""]', text)
            title = title_match.group(1) if title_match else "kuaishou_video"
            return {"title": title, "video_url": video_url, "cover": ""}
        return None

    def _find_cover_url(self, obj, depth=0) -> str:
        """递归查找封面图 URL（coverUrls / cover）"""
        if depth > 30:
            return ""
        if isinstance(obj, dict):
            # 快手特有字段：coverUrls 是一个列表，对象里有 url 字段
            cover_urls = obj.get("coverUrls") or obj.get("cover") or obj.get("thumbnail")
            if isinstance(cover_urls, list) and cover_urls:
                first = cover_urls[0]
                if isinstance(first, dict):
                    url = first.get("url") or first.get("uri")
                    if url and isinstance(url, str) and url.startswith("http"):
                        return url
                elif isinstance(first, str) and first.startswith("http"):
                    return first
            # 常规字符串字段
            for key in ("cover", "thumbnail", "poster"):
                val = obj.get(key)
                if val and isinstance(val, str) and val.startswith("http"):
                    return val
            for v in obj.values():
                result = self._find_cover_url(v, depth + 1)
                if result:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = self._find_cover_url(item, depth + 1)
                if result:
                    return result
        return ""

    def _try_mobile_access(self, short_url: str) -> Optional[dict]:
        """使用移动端 UA 访问"""
        headers = {**self.headers}

        try:
            resp = requests.get(short_url, headers=headers, timeout=self.timeout, allow_redirects=True)
            html = resp.text

            # 策略：从 script 块中提取
            video_data = self._strategy_script_json(html)
            if video_data:
                return video_data

            # 策略：window.INIT_STATE
            video_data = self._strategy_window_data(html)
            if video_data:
                return video_data

        except Exception:
            pass

        return None

    def _strategy_script_json(self, html: str) -> Optional[dict]:
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S | re.I)

        for sc in scripts:
            if '"caption"' not in sc:
                continue

            cap_m = re.search(r'"caption"\s*:\s*"([^"]{1,300})"', sc)
            caption = cap_m.group(1) if cap_m else 'kuaishou_video'

            url_pattern = r'"(?:url|playUrl|videoUrl)"\s*:\s*"(https?://[^"]+\.mp4[^"]*)"'
            mp4_urls = re.findall(url_pattern, sc, re.I)

            if not mp4_urls:
                _KS_CDN_PAT = r'https?://[^\s"\'<>]+(?:oskwai\.com|kwimgs\.com|ndcimgs\.com|yximgs\.com)[^\s"\'<>]*\.mp4[^\s"\'<>]*'
                mp4_urls = re.findall(_KS_CDN_PAT, sc)

            if mp4_urls:
                # 尝试提取封面
                cover = self._find_cover_url_in_script(sc)
                return {"title": caption, "video_url": mp4_urls[0], "cover": cover}

        return None

    def _find_cover_url_in_script(self, script_text: str) -> str:
        """从 script 文本中提取封面 URL"""
        # coverUrls 格式
        m = re.search(r'"coverUrls"\s*:\s*\[(\{[^\]]+\})\]', script_text)
        if m:
            url_m = re.search(r'"url"\s*:\s*"(https?://[^"]+)"', m.group(1))
            if url_m:
                return url_m.group(1)
        # cover 格式
        m = re.search(r'"cover"\s*:\s*"(https?://[^"]+)"', script_text)
        if m:
            return m.group(1)
        return ""

    def _strategy_window_data(self, html: str) -> Optional[dict]:
        patterns = [
            r'window\.INIT_STATE\s*=\s*',
            r'window\.v_data\s*=\s*',
        ]

        for pat in patterns:
            m = re.search(pat, html)
            if not m:
                continue

            brace_start = html.find('{', m.end())
            if brace_start == -1:
                continue

            json_str = self._extract_json_by_brace(html, brace_start)
            if not json_str:
                continue

            try:
                data = json.loads(json_str)
            except Exception:
                continue

            video_url = (
                self._find_value_by_key(data, 'srcNoMark') or
                self._find_value_by_key(data, 'playUrl') or
                self._find_video_in_json(data)
            )

            if isinstance(video_url, list):
                video_url = next((u for u in video_url if isinstance(u, str) and 'mp4' in u), None)

            if video_url:
                title = self._find_value_by_key(data, 'caption') or "kuaishou_video"
                cover = self._find_cover_url(data)
                return {"title": title, "video_url": video_url, "cover": cover}

        return None

    def _extract_json_by_brace(self, text: str, start: int) -> Optional[str]:
        if text[start] != '{':
            return None
        depth, in_str, escape = 0, False, False
        for i, ch in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if ch == '"' and not escape:
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return text[start: i + 1]
        return None

    def _find_value_by_key(self, obj, target_key: str):
        if isinstance(obj, dict):
            if target_key in obj:
                return obj[target_key]
            for v in obj.values():
                res = self._find_value_by_key(v, target_key)
                if res:
                    return res
        elif isinstance(obj, list):
            for item in obj:
                res = self._find_value_by_key(item, target_key)
                if res:
                    return res
        return None

    def _find_video_in_json(self, obj) -> Optional[str]:
        _KS_CDN = ('oskwai.com', 'kwimgs.com', 'ndcimgs.com', 'yximgs.com')

        def _is_video_url(s: str) -> bool:
            if not isinstance(s, str) or len(s) < 10:
                return False
            return '.mp4' in s or any(d in s for d in _KS_CDN)

        if isinstance(obj, dict):
            for key in ['srcNoMark', 'playUrl', 'videoUrl', 'mp4Url', 'url']:
                if key in obj and _is_video_url(obj[key]):
                    return obj[key]
            for v in obj.values():
                res = self._find_video_in_json(v)
                if res:
                    return res
        elif isinstance(obj, list):
            for item in obj:
                res = self._find_video_in_json(item)
                if res:
                    return res
        return None
