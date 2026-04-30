"""
Instagram解析服务
支持视频、图片以及多图轮播帖子(carousel_media)
"""
import html as html_mod
import json
import re
import requests
from typing import Optional, List, Dict
from app.services.base import BaseExtractor


class InstagramExtractor(BaseExtractor):
    """Instagram媒体解析器"""

    PLATFORM_NAME = "Instagram"

    def __init__(self):
        self.session = requests.Session()
        self.timeout = 30
        self.max_retries = 3
        # 多种 User-Agent 轮换使用
        self.user_agents = [
            "FacebookExternalHit/1.0 (+http://www.facebook.com/externalhit_uatext.php)",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        ]

    def extract(self, url: str) -> Optional[dict]:
        """从Instagram URL提取媒体信息"""
        normalized_url = self._normalize_url(url)
        if not normalized_url:
            return None

        print(f"[*] Instagram解析: {normalized_url}")

        page = None
        # 尝试多种 UA 和策略
        for ua_idx in range(len(self.user_agents)):
            for retry in range(self.max_retries):
                try:
                    headers = {
                        "User-Agent": self.user_agents[ua_idx],
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
                        "Accept-Encoding": "gzip, deflate",
                    }

                    resp = self.session.get(normalized_url, headers=headers, timeout=30, allow_redirects=True)
                    resp.raise_for_status()
                    page = resp.text
                    print(f"[*] 页面获取成功 (UA:{ua_idx}, retry:{retry})")
                    break
                except Exception as e:
                    print(f"[!] UA{ua_idx} retry{retry} 失败: {e}")
                    self.session = requests.Session()  # 重置 session
                    import time
                    time.sleep(1)  # 等待一下再重试

            if page:
                break

        if not page:
            print("[!] Instagram页面获取失败")
            return None

        og_title = self._extract_meta(page, "og:title") or self._extract_meta(page, "title")
        if og_title:
            og_title = html_mod.unescape(og_title)

        # 首先检查是否有视频（video_versions），优先级最高
        video_url = self._extract_video_url(page)
        if video_url:
            cover = html_mod.unescape(self._extract_meta(page, "og:image")) or ""
            # 检查是否是轮播帖子
            carousel_media = self._extract_carousel_media(page)
            if carousel_media and len(carousel_media) > 0:
                print(f"[*] 检测到视频+轮播帖子(carousel_media)，共{len(carousel_media)}个媒体")
                # 视频帖子作为第一项添加到轮播列表
                carousel_media.insert(0, {
                    "type": "video",
                    "display_url": cover,
                    "url": video_url,
                })
                return self.normalize_result({
                    "title": self._clean_title(og_title) or "Instagram video carousel",
                    "video_url": video_url,
                    "cover": cover,
                    "images": carousel_media,
                }, self.PLATFORM_NAME)
            else:
                print("[*] 检测到视频帖子")
                return self.normalize_result({
                    "title": self._clean_title(og_title) or "Instagram video",
                    "video_url": video_url,
                    "cover": cover,
                }, self.PLATFORM_NAME)

        # 尝试提取多图轮播帖子（无视频情况）
        carousel_media = self._extract_carousel_media(page)
        if carousel_media and len(carousel_media) > 0:
            print(f"[*] 检测到轮播帖子(carousel_media)，共{len(carousel_media)}个媒体")
            # 返回第一项
            first_media = carousel_media[0]
            return self.normalize_result({
                "title": self._clean_title(og_title) or "Instagram carousel",
                "video_url": "",
                "cover": first_media.get("display_url", ""),
                "images": carousel_media,
            }, self.PLATFORM_NAME)

        # 单图片帖子 - 使用 image_versions2 获取高清图
        image_url = self._extract_image_url(page)
        if image_url:
            return self.normalize_result({
                "title": self._clean_title(og_title) or "Instagram image",
                "video_url": "",
                "cover": image_url,
            }, self.PLATFORM_NAME)

        # 兜底：og:image
        og_image = self._extract_meta(page, "og:image")
        if og_image:
            return self.normalize_result({
                "title": self._clean_title(og_title) or "Instagram image",
                "video_url": "",
                "cover": og_image,
            }, self.PLATFORM_NAME)

        print("[!] 未能提取到媒体信息")
        return None

    def _normalize_url(self, url: str) -> Optional[str]:
        """标准化Instagram URL"""
        url = url.strip()

        # 支持多种格式
        patterns = [
            r'instagram\.com/(?:r/)?(reel|reels|p|tv|shorts)/([A-Za-z0-9_-]+)',
            r'instagr\.am/([A-Za-z0-9_-]+)',
        ]

        for pattern in patterns:
            m = re.search(pattern, url)
            if m:
                shortcode = m.group(2) if m.lastindex >= 2 else m.group(1)
                return f"https://www.instagram.com/p/{shortcode}/"

        return None

    def _extract_meta(self, html: str, property_name: str) -> Optional[str]:
        """提取OG标签"""
        patterns = [
            rf'<meta[^>]+property=["\']({re.escape(property_name)})["\'][^>]+content=["\']([^"\']*)["\']',
            rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']({re.escape(property_name)})["\']',
            rf'<meta[^>]+name=["\']({re.escape(property_name)})["\'][^>]+content=["\']([^"\']*)["\']',
            rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']({re.escape(property_name)})["\']',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                return m.group(2) if len(m.groups()) > 1 and m.group(2) else m.group(1)
        return None

    def _extract_video_url(self, page: str) -> Optional[str]:
        """从页面提取视频URL"""
        # 尝试从video_versions提取
        m = re.search(r'"video_versions"\s*:\s*\[', page)
        if m:
            brace_start = page.find("[", m.start() + len('"video_versions"'))
            if brace_start != -1:
                arr_str = self._extract_array_by_bracket(page, brace_start)
                if arr_str:
                    try:
                        versions = json.loads(arr_str)
                        if versions:
                            versions.sort(key=lambda v: v.get("width", 0) * v.get("height", 0), reverse=True)
                            return html_mod.unescape(versions[0].get("url", ""))
                    except:
                        pass

        # 尝试从og:video提取
        og_video = self._extract_meta(page, "og:video") or self._extract_meta(page, "og:video:secure_url")
        if og_video:
            return og_video

        return None

    def _extract_image_url(self, page: str) -> Optional[str]:
        """从页面提取高清图片URL（使用image_versions2）"""
        # 查找 image_versions2
        m = re.search(r'"image_versions2"\s*:\s*\{', page)
        if not m:
            return None

        brace_start = page.find("{", m.start() + len('"image_versions2"'))
        if brace_start == -1:
            return None

        obj_str = self._extract_json_by_brace(page, brace_start)
        if not obj_str:
            return None

        try:
            data = json.loads(obj_str)
            candidates = data.get("candidates", [])
            if not candidates:
                return None

            # 取最大分辨率
            candidates.sort(key=lambda c: c.get("width", 0) * c.get("height", 0), reverse=True)
            best = candidates[0]
            url = best.get("url", "")
            if url:
                return html_mod.unescape(url)
        except:
            pass

        return None

    def _extract_carousel_media(self, page: str) -> List[Dict]:
        """提取轮播帖子的所有媒体（carousel_media）"""
        media_list = []

        # 查找 carousel_media 数组
        m = re.search(r'"carousel_media"\s*:\s*\[', page)
        if not m:
            return media_list

        brace_start = page.find("[", m.start() + len('"carousel_media"'))
        if brace_start == -1:
            return media_list

        carousel_str = self._extract_array_by_bracket(page, brace_start)
        if not carousel_str:
            return media_list

        try:
            carousel_data = json.loads(carousel_str)
        except:
            return media_list

        for item in carousel_data:
            if not isinstance(item, dict):
                continue

            media_type = item.get("media_type", 1)  # 1=图片, 2=视频
            display_url = ""

            # 从 image_versions2 提取高清图
            iv2 = item.get("image_versions2") or {}
            candidates = iv2.get("candidates", [])
            if candidates:
                candidates.sort(key=lambda c: c.get("width", 0) * c.get("height", 0), reverse=True)
                display_url = candidates[0].get("url", "")

            if not display_url:
                display_url = item.get("display_url", "")

            if display_url:
                media_info = {
                    "type": "video" if media_type == 2 else "image",
                    "display_url": html_mod.unescape(display_url),
                }

                # 如果是视频，提取视频URL
                if media_type == 2:
                    video_versions = item.get("video_versions", [])
                    if video_versions:
                        video_versions.sort(key=lambda v: v.get("width", 0) * v.get("height", 0), reverse=True)
                        media_info["url"] = html_mod.unescape(video_versions[0].get("url", ""))

                media_list.append(media_info)

        return media_list

    def _extract_array_by_bracket(self, text: str, start: int) -> Optional[str]:
        """提取括号内的数组"""
        if text[start] != "[":
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
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return text[start: i + 1]
        return None

    def _extract_json_by_brace(self, text: str, start: int) -> Optional[str]:
        """提取括号内的JSON对象"""
        if text[start] != "{":
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
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start: i + 1]
        return None

    def _clean_title(self, text: str) -> str:
        """清理标题"""
        if not text:
            return ""
        text = re.sub(r'\s*on Instagram\b.*', '', text)
        text = re.sub(r'\s*·\s*Instagram\s*$', '', text)
        return text.strip()[:100]
