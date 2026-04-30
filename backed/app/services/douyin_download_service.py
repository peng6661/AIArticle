"""
抖音视频解析服务
业务逻辑来自原始脚本，完全保留
"""
import json
import re
import urllib.parse
import requests
from typing import Optional
from app.services.base import BaseExtractor
from app.core.config import get_settings


class VideoBlockedError(Exception):
    """视频已被删除/设为私密"""
    pass


class DouyinExtractor(BaseExtractor):
    """抖音视频解析器"""

    PLATFORM_NAME = "抖音"

    def __init__(self):
        cfg = get_settings()
        self.headers = {
            "User-Agent": cfg.douyin_user_agent,
            "Referer": cfg.douyin_referer,
        }
        self.timeout_short = cfg.douyin_timeout_short
        self.timeout_medium = cfg.douyin_timeout_medium
        self.timeout_download = cfg.douyin_timeout_download

    def log(self, step: str, message: str):
        print(f"[*] {step}: {message}")

    def extract(self, share_text: str) -> Optional[dict]:
        """从抖音分享文本提取视频信息"""
        url_match = re.search(r'https://v\.douyin\.com/[A-Za-z0-9_-]+/?', share_text)
        if not url_match:
            return None

        short_url = url_match.group(0)
        try:
            response = requests.get(short_url, headers=self.headers, timeout=self.timeout_medium)
            html = response.text

            # 策略1: _ROUTER_DATA (支持新旧两种数据结构)
            video_data = self._strategy_router_data(html)
            if not video_data:
                # 策略2: RENDER_DATA
                render_result = self._strategy_render_data(html)
                if render_result:
                    video_data = {"title": "douyin_video", **render_result}
                else:
                    # 策略3: HTML source 标签
                    video_url = self._strategy_html_tags(html)
                    video_data = {"title": "douyin_video", "url": video_url, "cover": ""} if video_url else None

            # 检测是否为失效/私密视频
            self._check_video_blocked(html)

            if video_data and video_data.get('url'):
                final_res = self._get_final_media_url(video_data['url'])
                video_data['url'] = final_res['media_url']
                return self.normalize_result(video_data, self.PLATFORM_NAME)
        except VideoBlockedError as e:
            # 将失效信息作为特殊结果返回（通过 normalize_result 的 error 字段传递）
            self.log("BLOCKED", str(e))
            return {"error": str(e), "error_type": "blocked"}
        except Exception as e:
            self.log("Error", f"解析失败: {e}")
        return None

    def _strategy_router_data(self, html: str) -> Optional[dict]:
        """策略1: 从 window._ROUTER_DATA 提取（支持新旧两种数据结构）"""
        pattern = r'window\._ROUTER_DATA\s*=\s*(.*?)</script>'
        match = re.search(pattern, html, re.S)
        if match:
            try:
                raw_json = match.group(1).strip().rstrip(';')
                data = json.loads(raw_json)

                # ── 优先从 videoInfoRes (新版 iesdouyin 页面结构) 提取 ──
                new_result = self._extract_from_video_info_res(data)
                if new_result:
                    return new_result

                # ── 旧版：递归查找 play_addr ──
                title = self._find_value_by_key(data, 'desc') or "douyin_video"
                url = self._find_video_in_json(data)
                cover = self._find_cover_in_json(data)
                return {"title": title, "url": url, "cover": cover}
            except Exception:
                pass
        return None

    def _extract_from_video_info_res(self, data: dict) -> Optional[dict]:
        """
        从新版 _ROUTER_DATA 的 loaderData.video_(id)/page.videoInfoRes 中提取视频信息。
        
        新版数据结构（2025年后抖音分享页改版）：
          _ROUTER_DATA.loaderData
            ├── "video_layout" → None (SSR 占位)
            └── "video_(id)/page"
                └── videoInfoRes
                    ├── item_list: [ { video: { play_addr, cover, ... }, desc } ]
                    └── filter_list: [ { filter_reason, notice, detail_msg } ]
        """
        loader_data = data.get('loaderData')
        if not isinstance(loader_data, dict):
            return None

        # 找到包含 /page 的 key（动态路由 key，格式如 "video_(id)/page"）
        page_data = None
        for key in loader_data:
            if '/page' in str(key):
                page_data = loader_data[key]
                break

        if not isinstance(page_data, dict):
            return None

        video_info = page_data.get('videoInfoRes')
        if not isinstance(video_info, dict):
            return None

        item_list = video_info.get('item_list', [])

        # 有正常视频数据
        if item_list and len(item_list) > 0:
            item = item_list[0]
            title = item.get('desc', '') or "douyin_video"

            # 视频地址
            video_obj = item.get('video', {})
            play_addr = video_obj.get('play_addr', {})
            url_list = play_addr.get('url_list', []) if isinstance(play_addr, dict) else []
            url = url_list[0] if url_list else ''

            # 封面图 - 多个可能的字段
            cover = ''
            for cover_key in ('cover', 'origin_cover', 'dynamic_cover', 'thumbnail'):
                cover_obj = video_obj.get(cover_key, {})
                if isinstance(cover_obj, dict):
                    c_url_list = cover_obj.get('url_list', [])
                    if c_url_list and isinstance(c_url_list, list) and c_url_list[0]:
                        cover = c_url_list[0]
                        break
                    elif cover_obj.get('url') and str(cover_obj['url']).startswith('http'):
                        cover = cover_obj['url']
                        break
                elif isinstance(cover_obj, str) and cover_obj.startswith('http'):
                    cover = cover_obj
                    break

            self.log("VideoInfoRes", f"提取到: title={title[:30]}..., video={'有' if url else '无'}, cover={'有' if cover else '无'}")
            return {"title": title, "url": url, "cover": cover}

        return None

    def _check_video_blocked(self, html: str):
        """检测视频是否已被删除/设为私密/失效"""
        pattern = r'window\._ROUTER_DATA\s*=\s*(.*?)</script>'
        match = re.search(pattern, html, re.S)
        if not match:
            return

        try:
            raw_json = match.group(1).strip().rstrip(';')
            data = json.loads(raw_json)

            loader_data = data.get('loaderData', {})
            if not isinstance(loader_data, dict):
                return

            page_data = None
            for key in loader_data:
                if '/page' in str(key):
                    page_data = loader_data[key]
                    break

            if not isinstance(page_data, dict):
                return

            video_info = page_data.get('videoInfoRes', {})
            if not isinstance(video_info, dict):
                return

            item_list = video_info.get('item_list', [])
            filter_list = video_info.get('filter_list', [])

            # item_list 为空 + 有过滤信息 → 视频失效
            if (not item_list or len(item_list) == 0) and filter_list:
                for f in filter_list:
                    reason = f.get('filter_reason', '')
                    notice = f.get('notice', '')
                    detail = f.get('detail_msg', '')

                    # 常见失效原因映射
                    reason_map = {
                        'status_self_see': '该作品已设为私密或已被删除',
                        'status_delete': '该作品已删除',
                        'status_review': '该作品正在审核中',
                        'status_illegal': '该作品因违规已被下架',
                        'status_block': '该作品已被屏蔽',
                    }

                    msg = reason_map.get(reason, detail or notice or '该视频无法访问')
                    raise VideoBlockedError(msg)
        except VideoBlockedError:
            raise
        except Exception:
            pass

    def _find_video_in_json(self, obj) -> Optional[str]:
        """递归查找视频URL"""
        if isinstance(obj, dict):
            if 'play_addr' in obj and isinstance(obj['play_addr'], dict):
                urls = obj['play_addr'].get('url_list', [])
                if urls:
                    return urls[0]
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

    def _find_cover_in_json(self, obj, depth=0) -> Optional[str]:
        """递归查找封面图URL"""
        if depth > 30:
            return None
        if isinstance(obj, dict):
            # 常见封面字段
            for key in ('cover', 'thumbnail', 'thumb', 'img', 'poster'):
                val = obj.get(key)
                if val and isinstance(val, str) and val.startswith('http'):
                    print(f"[*] 找到封面 (key={key}): {val[:80]}...")
                    return val
                # cover 可能是对象，包含 url_list 字段
                if val and isinstance(val, dict):
                    # 直接有 url 字段
                    url = val.get('url') or val.get('uri')
                    if url and isinstance(url, str) and url.startswith('http'):
                        print(f"[*] 找到封面 (key={key}, url): {url[:80]}...")
                        return url
                    # url_list 是列表，取第一个
                    url_list = val.get('url_list')
                    if isinstance(url_list, list) and url_list:
                        first = url_list[0]
                        if isinstance(first, str) and first.startswith('http'):
                            print(f"[*] 找到封面 (key={key}, url_list): {first[:80]}...")
                            return first
            for v in obj.values():
                res = self._find_cover_in_json(v, depth + 1)
                if res:
                    return res
        elif isinstance(obj, list):
            for item in obj:
                res = self._find_cover_in_json(item, depth + 1)
                if res:
                    return res
        return None

    def _find_value_by_key(self, obj, target_key: str):
        """递归查找指定键值"""
        if isinstance(obj, dict):
            if target_key in obj:
                return obj[target_key]
            for v in obj.values():
                res = self._find_value_by_key(v, target_key)
                if res:
                    return res
        return None

    def _strategy_render_data(self, html: str) -> Optional[dict]:
        """策略2: 从 RENDER_DATA 提取"""
        pattern = r'id="RENDER_DATA"[^>]*>(.*?)</script>'
        match = re.search(pattern, html, re.S)
        if match:
            try:
                data = json.loads(urllib.parse.unquote(match.group(1).strip()))
                url = self._find_video_in_json(data)
                cover = self._find_cover_in_json(data)
                return {"url": url, "cover": cover} if url else None
            except Exception:
                pass
        return None

    def _strategy_html_tags(self, html: str) -> Optional[str]:
        """策略3: 从 HTML source 标签提取"""
        pattern = r'<source[^>]+src=["\']([^"\']+)["\']'
        sources = re.findall(pattern, html, re.S)
        return sources[0] if sources else None

    def _get_final_media_url(self, play_url: str) -> dict:
        """获取最终媒体URL"""
        real_play_url = play_url.replace('playwm', 'play')
        if not real_play_url.startswith('http'):
            real_play_url = 'https:' + real_play_url
        res = requests.get(
            real_play_url,
            headers=self.headers,
            allow_redirects=False,
            timeout=self.timeout_short,
        )
        return {"media_url": res.headers.get('Location', real_play_url)}
