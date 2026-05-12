"""
X (Twitter) 视频/图片解析服务

技术方案：
1. 主力：curl_cffi（模拟浏览器 TLS 指纹）+ Twitter Syndication API
   - 获取推文完整信息：文本、用户、视频 MP4 直链、图片列表
2. 备用：__INITIAL_STATE__ 解析
3. 下载：直接流式转发 Twitter CDN 的 MP4 直链（无需 yt-dlp）
"""

import html as html_mod
import json
import os
import re
import shutil
import tempfile
import threading
import queue
from pathlib import Path
from typing import Optional, Generator

from curl_cffi import requests as cffi_requests

from app.services.base import BaseExtractor
from app.api._pipeline_utils import sanitize_filename


class XVideoExtractor(BaseExtractor):
    """X/Twitter 视频/图片解析器（curl_cffi + Syndication API）"""

    PLATFORM_NAME = "X"

    # 代理设置 - 仅在显式设置 X_PROXY 环境变量时生效，未设置则直连
    # 示例：export X_PROXY=http://127.0.0.1:7897
    PROXY_URL: Optional[str] = os.environ.get("X_PROXY") or None

    # Bearer Token (Twitter 公开的 OAuth2 bearer)
    BEARER_TOKEN = (
        "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
        "%3D1Zv7ttfk8LF81IUq16cHjhLTvJuFA33AGWWjCpTnA"
    )

    # Syndication API 端点
    SYNDICATION_API = "https://cdn.syndication.twimg.com/tweet-result"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://x.com/",
        }
        # 使用 curl_cffi 模拟浏览器 TLS 指纹；有代理时才传入 proxy
        session_kwargs: dict = {"impersonate": "chrome"}
        if self.PROXY_URL:
            session_kwargs["proxy"] = self.PROXY_URL
        self.session = cffi_requests.Session(**session_kwargs)
        self.timeout = 30

    def extract(self, url: str) -> Optional[dict]:
        """
        从 X/Twitter URL 提取媒体信息。

        策略：
        1. Syndication API（主力）：返回视频 MP4 直链 + 图片 + 文本
        2. __INITIAL_STATE__ 降级（备用）
        """
        # ── 方案1：Syndication API ──
        result = self._extract_with_syndication(url)
        if result:
            return result

        # ── 方案2：__INITIAL_STATE__ 降级 ──
        result = self._extract_with_initial_state(url)
        if result:
            return result

        return None

    # ════════════════════════════════════════
    #  方案1：Syndication API（主力）
    # ════════════════════════════════════════

    def _extract_with_syndication(self, url: str) -> Optional[dict]:
        """使用 Twitter Syndication API 提取推文媒体信息
        
        该 API 是 Twitter 官方的 syndication 服务，用于嵌入推文。
        返回完整的推文数据，包括：
        - 推文文本、作者信息
        - 视频 MP4 直链（多画质）
        - 图片 URL 列表
        - 封面图
        """
        tweet_id = self._parse_tweet_id(url)
        if not tweet_id:
            return None

        try:
            params = {
                "id": tweet_id,
                "lang": "en",
                "token": "xyz",
            }
            
            resp = self.session.get(
                self.SYNDICATION_API,
                params=params,
                headers=self.headers,
                timeout=self.timeout,
            )
            
            if resp.status_code != 200:
                print(f"[X] Syndication API 返回 {resp.status_code}")
                return None
            
            data = resp.json()

            # 检查是否为 tombstone（已删除/受限的推文）
            if data.get("__typename") == "TweetTombstone" or "tombstone" in data:
                print(f"[X] 推文已删除或受限: {tweet_id}")
                return self._make_text_result(url, tweet_id, data)

            # 检查是否真的有推文数据
            if data.get("__typename") != "Tweet":
                print(f"[X] 非推文类型: {data.get('__typename')}")
                return None
            
            # ── 提取基本信息 ──
            raw_text = data.get("text", "") or ""
            user = data.get("user", {}) or {}
            screen_name = user.get("screen_name", "") or ""
            name = user.get("name", "") or ""

            # 清理标题
            title = raw_text[:150].strip()
            if not title:
                title = f"X_Tweet_{tweet_id}"
            elif screen_name:
                title = f"@{screen_name}: {title}"

            # ── 提取视频信息 ──
            video_data = data.get("video")
            video_url = ""
            cover_url = ""
            duration = 0

            if isinstance(video_data, dict):
                variants = video_data.get("variants", [])
                if variants:
                    # 选择最高画质的 MP4
                    mp4_variants = [
                        v for v in variants
                        if isinstance(v, dict) and v.get("type") == "video/mp4"
                    ]
                    if mp4_variants:
                        # 选最后一个（通常按画质升序排列）
                        best = mp4_variants[-1]
                        video_url = best.get("src", "")

                    # 也记录所有画质供前端选择
                    all_mp4 = [
                        {"url": v["src"], "type": v.get("type", "")}
                        for v in variants
                        if isinstance(v, dict) and "mp4" in v.get("type", "")
                    ]

                cover_url = video_data.get("poster", "") or ""
                duration = (video_data.get("durationMs", 0) or 0) // 1000

            # ── 提取图片信息 ──
            photos = data.get("photos", []) or []
            images_list = []
            
            for photo in photos:
                if isinstance(photo, dict):
                    img_url = photo.get("image_url") or photo.get("url", "")
                    if img_url:
                        images_list.append({
                            "type": "image",
                            "display_url": img_url,
                            "url": img_url,
                        })

            # 如果没有视频也没有图片但有 mediaDetails，尝试从中提取
            if not video_url and not images_list:
                media_details = data.get("mediaDetails", []) or []
                for md in media_details:
                    if isinstance(md, dict):
                        md_url = md.get("media_url_https", "")
                        if md_url and "pbs.twimg.com" in md_url:
                            images_list.append({
                                "type": "image",
                                "display_url": md_url,
                                "url": md_url,
                            })

            # ── 构建结果 ──
            result = self.normalize_result({
                "title": title,
                "video_url": video_url,
                "cover": cover_url,
                "images": images_list,
            }, self.PLATFORM_NAME)

            result["_original_url"] = url
            result["author_name"] = name
            result["author_screen_name"] = screen_name
            result["duration"] = duration
            result["tweet_id"] = tweet_id
            result["tweet_text"] = raw_text

            # 标记媒体类型
            has_video = bool(video_url)
            has_images = len(images_list) > 0

            if has_video:
                result["media_type"] = "video"
                result["_needs_ytdl"] = False  # 有直链，不需要 yt-dlp
                # 存储所有画质选项
                if 'all_mp4' in dir():
                    result["_video_variants"] = all_mp4
            elif has_images:
                result["media_type"] = "image"
                result["image_count"] = len(images_list)
                result["_needs_ytdl"] = False
            else:
                # 有推文数据但没有媒体内容
                result["media_type"] = "text"
                result["image_count"] = 0
                result["_no_media"] = True

            print(f"[X] Syndication 解析成功: "
                  f"type={result['media_type']}, "
                  f"video={'YES' if has_video else 'NO'}, "
                  f"images={len(images_list)}")
            return result

        except Exception as e:
            print(f"[X] Syndication API 错误: {e}")
            return None

    # ════════════════════════════════════════
    #  方案2：__INITIAL_STATE__ 降级（备用）
    # ════════════════════════════════════════

    def _extract_with_initial_state(self, url: str) -> Optional[dict]:
        """从 __INITIAL_STATE__ JSON 提取视频信息（仅支持含视频 variants 的推文）"""
        tweet_id = self._parse_tweet_id(url)
        if not tweet_id:
            return None

        html = self._fetch_page(url)
        if not html:
            return None

        data = self._parse_initial_state(html)
        if not data:
            return None

        all_variants = self._find_all_variants(data)
        if not all_variants:
            return None

        mp4_variants = []
        seen_urls = set()
        for vs in all_variants:
            for v in vs:
                vurl = v.get("url", "")
                if "video/mp4" in v.get("content_type", "") and vurl not in seen_urls:
                    vurl = html_mod.unescape(vurl)
                    mp4_variants.append({
                        "url": vurl,
                        "bitrate": v.get("bitrate", 0),
                    })
                    seen_urls.add(vurl)

        if not mp4_variants:
            return None

        selected = max(mp4_variants, key=lambda v: v["bitrate"])
        
        tweet_text = self._find_value(data, "text") or ""
        screen_name = self._find_value(data, "screen_name") or ""
        title = f"@{screen_name}: {tweet_text[:50]}" if tweet_text and screen_name else f"X_{tweet_id}"
        cover_url = self._find_cover_url(data)

        result = self.normalize_result({
            "title": title,
            "video_url": selected["url"],
            "cover": cover_url,
        }, self.PLATFORM_NAME)

        result["_needs_ytdl"] = False
        result["_original_url"] = url
        result["media_type"] = "video"
        return result

    # ════════════════════════════════════════
    #  辅助方法：构建无媒体结果
    # ════════════════════════════════════════

    def _make_text_result(self, url: str, tweet_id: str, synd_data: dict) -> Optional[dict]:
        """构建「推文存在但无可下载媒体」的结果"""
        text = (synd_data.get("text", "") or "")[:150]
        title = text or f"X_Tweet_{tweet_id}"
        
        user = synd_data.get("user", {}) or {}
        sn = user.get("screen_name", "") or ""
        if sn and text:
            title = f"@{sn}: {title}"

        result = self.normalize_result({
            "title": title,
            "video_url": "",
            "cover": "",
        }, self.PLATFORM_NAME)

        result["_original_url"] = url
        result["_needs_ytdl"] = False
        result["media_type"] = "text"
        result["image_count"] = 0
        result["_no_media"] = True
        result["tweet_id"] = tweet_id
        return result

    # ════════════════════════════════════════
    #  下载方法
    # ════════════════════════════════════════

    def download(self, media_data: dict, save_dir: str = None) -> Optional[Path]:
        """
        下载 X/Twitter 媒体到本地。
        
        优先使用 CDN 直链（无需 yt-dlp），
        仅在无直链时回退到 yt-dlp。
        """
        if not save_dir:
            return None

        output_dir = Path(save_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        video_url = media_data.get("video_url", "")
        
        # 方案 A：使用 CDNL 直接下载
        if video_url:
            try:
                safe_title = sanitize_filename(
                    media_data.get("title", "x_media"))

                ext = ".mp4"
                content_type = ""

                # 先 HEAD 探测文件名和大小
                head_resp = self.session.head(
                    video_url,
                    headers={"Referer": "https://x.com/"},
                    timeout=15,
                )
                ct_header = head_resp.headers.get("Content-Disposition", "")
                if "filename=" in ct_header:
                    fn_match = re.search(r'filename="?([^";\n]+)"?', ct_header)
                    if fn_match:
                        safe_title = sanitize_filename(fn_match.group(1))

                output_path = output_dir / f"{safe_title}{ext}"
                
                resp = self.session.get(
                    video_url,
                    headers={"Referer": "https://x.com/"},
                    timeout=120,
                    stream=True,
                )
                
                with open(output_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=512 * 1024):
                        if chunk:
                            f.write(chunk)
                
                if output_path.exists() and output_path.stat().st_size > 10000:
                    return output_path
                    
            except Exception as e:
                print(f"[X] 直链下载失败: {e}, 回退到 yt-dlp")

        # 方案 B：回退到 yt-dlp
        url = media_data.get("_original_url", "")
        if url:
            return self._download_with_ytdlp(media_data, save_dir)

        return None

    def stream_to_iterator(self, url_or_data) -> Generator[bytes, None, None]:
        """
        流式读取 X/Twitter 视频，yield 二进制 chunks。
        
        优先从 CDN 直链流式读取，
        无直链时回退到 yt-dlp。
        
        参数可以是：
        - str: 原始推文 URL（走 extract 再下载）
        - dict: 已解析的 media_data（直接用 video_url 直链）
        """
        video_url = ""
        original_url = ""
        cover_url = ""

        if isinstance(url_or_data, dict):
            video_url = url_or_data.get("video_url", "")
            original_url = url_or_data.get("_original_url", "")
            cover_url = url_or_data.get("cover_url", "")
        else:
            original_url = url_or_data
            # 需要先提取
            extracted = self.extract(original_url)
            if extracted:
                video_url = extracted.get("video_url", "")
                cover_url = extracted.get("cover_url", "")

        # 方案 A：CDN 直链流式转发
        if video_url:
            chunk_size = 512 * 1024  # 512KB
            try:
                resp = self.session.get(
                    video_url,
                    headers={
                        **self.headers,
                        "Referer": "https://x.com/",
                    },
                    timeout=60,
                    stream=True,
                )
                resp.raise_for_status()
                
                total_size = 0
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if chunk:
                        total_size += len(chunk)
                        yield chunk
                
                print(f"[X] 流式转发完成: {total_size / 1024 / 1024:.2f} MB")
                return
                
            except Exception as e:
                print(f"[X] CDN 直链流式失败: {e}")

        # 方案 B：回退到 yt-dlp
        if original_url:
            yield from self._stream_with_ytdlp(original_url)
            return

        raise Exception("X/Twitter: 无法获取视频流（既没有直链接也无法通过 yt-dlp 获取）")

    # ════════════════════════════════════════
    #  yt-dlp 回退方法
    # ════════════════════════════════════════

    def _download_with_ytdlp(self, media_data: dict, save_dir: str) -> Optional[Path]:
        """用 yt-dlp 回退下载"""
        url = media_data.get("_original_url", "")
        if not url:
            return None

        try:
            import yt_dlp

            output_dir = Path(save_dir)
            safe_title = sanitize_filename(
                media_data.get("title", "X_media"))
            output_template = str(output_dir / f"{safe_title}.%(ext)s")

            opts = {
                "quiet": True,
                "no_warnings": True,
                "nocheckcertificate": True,
                "format": "best[ext=mp4]/best[ext=webp]/best[ext=jpg]/best",
                "outtmpl": output_template,
            }

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)

            if not info:
                return None

            expected_ext = info.get("ext", "mp4")
            expected_filename = f"{safe_title}.{expected_ext}"
            downloaded_path = output_dir / expected_filename

            if downloaded_path.exists():
                return downloaded_path

            candidates = list(output_dir.glob(f"{safe_title}*"))
            if candidates:
                return max(candidates, key=lambda p: p.stat().st_mtime)

            return None

        except ImportError:
            print("[X] yt-dlp 未安装")
            return None
        except Exception as e:
            print(f"[X] yt-dlp 下载失败: {e}")
            return None

    def _stream_with_ytdlp(self, url: str) -> Generator[bytes, None, None]:
        """用 yt-dlp 回退流式下载"""
        temp_dir = tempfile.mkdtemp(prefix="x_stream_")
        safe_title = "x_stream"
        output_template = str(Path(temp_dir) / f"{safe_title}.%(ext)s")

        opts = {
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "format": "best[ext=mp4]/best",
            "outtmpl": output_template,
        }

        result_queue: queue.Queue = queue.Queue()
        download_done = threading.Event()

        def _download():
            try:
                import yt_dlp
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                candidates = list(Path(temp_dir).glob(f"{safe_title}*"))
                file_path = (
                    max(candidates, key=lambda p: p.stat().st_mtime)
                    if candidates else None
                )
                result_queue.put(("ok", str(file_path) if file_path else None))
            except Exception as e:
                result_queue.put(("error", str(e)))
            finally:
                download_done.set()

        t = threading.Thread(target=_download, daemon=True)
        t.start()

        download_done.wait()
        t.join(timeout=600)

        status, value = result_queue.get()

        if status == "error":
            raise Exception(f"X/Twitter yt-dlp 流式失败: {value}")

        if not value or not Path(value).exists():
            raise Exception("X/Twitter yt-dlp 下载完成但文件不存在")

        chunk_size = 512 * 1024
        try:
            with open(value, "rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # ════════════════════════════════════════
    #  __INITIAL_STATE__ 辅助方法（降级用）
    # ════════════════════════════════════════

    def _find_cover_url(self, obj, depth=0) -> str:
        """递归查找封面图 URL"""
        if depth > 30:
            return ""
        if isinstance(obj, dict):
            media_url = obj.get("media_url_https") or obj.get("mediaUrl")
            if media_url and isinstance(media_url, str) and media_url.startswith("http"):
                return media_url
            poster = obj.get("poster") or obj.get("posterUrl") or obj.get("thumbnailUrl")
            if poster and isinstance(poster, str) and poster.startswith("http"):
                return poster
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

    def _parse_tweet_id(self, url: str) -> Optional[str]:
        m = re.search(r'(?:status|statuses)/(\d{15,20})', url)
        return m.group(1) if m else None

    def _fetch_page(self, url: str) -> Optional[str]:
        tweet_id = self._parse_tweet_id(url)
        if tweet_id:
            url = f"https://x.com/i/status/{tweet_id}"
        try:
            resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            resp.raise_for_status()
            return resp.text
        except Exception:
            return None

    def _parse_initial_state(self, html: str) -> Optional[dict]:
        m = re.search(r'window\.__INITIAL_STATE__\s*=\s*', html)
        if not m:
            return None
        brace_start = html.find("{", m.end())
        if brace_start == -1:
            return None
        js = self._extract_json_by_brace(html, brace_start)
        if not js:
            return None
        try:
            return json.loads(js)
        except Exception:
            try:
                return json.loads(js.rstrip(";").strip())
            except Exception:
                return None

    def _find_all_variants(self, obj, depth=0) -> list:
        if depth > 30:
            return []
        results = []
        if isinstance(obj, dict):
            if "variants" in obj and isinstance(obj["variants"], list):
                results.append(obj["variants"])
            for v in obj.values():
                results.extend(self._find_all_variants(v, depth + 1))
        elif isinstance(obj, list):
            for item in obj:
                results.extend(self._find_all_variants(item, depth + 1))
        return results

    def _find_value(self, obj, key: str, depth=0):
        if depth > 20:
            return None
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for v in obj.values():
                r = self._find_value(v, key, depth + 1)
                if r:
                    return r
        elif isinstance(obj, list):
            for item in obj:
                r = self._find_value(item, key, depth + 1)
                if r:
                    return r
        return None

    def _extract_json_by_brace(self, text: str, start: int) -> Optional[str]:
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
