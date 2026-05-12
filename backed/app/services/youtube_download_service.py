"""
YouTube视频解析服务

重要：YouTube 视频的 CDN 直链有时效性（几秒~几分钟），不能像其他平台那样
先提取直链再用 requests 下载。必须用 yt-dlp 自身的下载功能直接保存到本地。

【使用说明】
1. 用浏览器扩展（如 "Get cookies.txt LOCALLY"）导出 cookies 文件
2. 放到 backed/cookies_youtube.txt
3. 确保 Chrome 已登录 YouTube 账号
"""
import yt_dlp
import asyncio
import threading
import queue
import shutil
import re
import tempfile
from pathlib import Path
from typing import Optional, AsyncIterator, Dict, Any
from dataclasses import dataclass, field
from app.services.base import BaseExtractor
from app.core.config import get_settings

# 后端目录（backed/），用于解析相对路径的 cookies 文件
_BACKED_DIR = Path(__file__).parent.parent.parent


def _get_js_runtime_opts() -> dict:
    """
    自动检测并配置 yt-dlp 的 JavaScript Runtime。
    新版 yt-dlp 需要 JS Runtime 来生成 PO Token，否则 YouTube 会返回机器人验证错误。
    支持：node / deno / bun / quickjs
    """
    settings = get_settings()
    js_runtime_cfg = settings.youtube_js_runtime  # "auto" / "node:/path/to/node" / "" / "none"

    if not js_runtime_cfg or js_runtime_cfg.lower() == "none":
        return {}

    if js_runtime_cfg.lower() == "auto":
        # 自动查找：依次检测 node / deno / bun
        for runtime_name in ("node", "deno", "bun"):
            runtime_path = shutil.which(runtime_name)
            if runtime_path:
                print(f"[YouTube] 自动检测到 JS Runtime: {runtime_name} -> {runtime_path}")
                return {"js_runtimes": {runtime_name: {"path": runtime_path}}}
        print("[YouTube] 警告: 未找到 JS Runtime（node/deno/bun），YouTube 解析可能受限")
        return {}

    # 手动配置，格式：<runtime_name> 或 <runtime_name>:<path>
    if ":" in js_runtime_cfg:
        parts = js_runtime_cfg.split(":", 1)
        runtime_name = parts[0].strip()
        runtime_path = parts[1].strip()
    else:
        runtime_name = js_runtime_cfg.strip()
        runtime_path = shutil.which(runtime_name) or ""

    if runtime_path:
        print(f"[YouTube] 使用 JS Runtime: {runtime_name} -> {runtime_path}")
        return {"js_runtimes": {runtime_name: {"path": runtime_path}}}
    else:
        print(f"[YouTube] 警告: 配置的 JS Runtime '{runtime_name}' 未找到")
        return {}


def _get_youtube_cookies_opts() -> dict:
    """
    根据配置返回 yt-dlp 的 cookies 相关选项。

    仅支持 file 模式：从 Netscape 格式的 cookies.txt 文件读取。
    请使用浏览器扩展（如 "Get cookies.txt LOCALLY"）手动导出 cookie 文件。
    """
    settings = get_settings()
    cookies_opts = {}
    cookies_source = settings.youtube_cookies_source

    if cookies_source == "none":
        print("[YouTube] cookies_source=none，不使用 cookies（仅适用于完全公开视频）")
        return {}

    elif cookies_source == "file":
        cookies_file = settings.youtube_cookies_file
        if cookies_file:
            # 支持相对路径（相对于 backed/ 目录）
            cookies_path = Path(cookies_file)
            if not cookies_path.is_absolute():
                cookies_path = _BACKED_DIR / cookies_file

            if cookies_path.exists():
                cookies_opts["cookiefile"] = str(cookies_path)
                print(f"[YouTube] 使用 cookies 文件: {cookies_path}")
            else:
                print(f"[YouTube] 警告: cookies 文件不存在: {cookies_path}")
                print(f"[YouTube] 请使用 'Get cookies.txt LOCALLY' Chrome 扩展导出 cookie")
        else:
            print("[YouTube] 警告: cookies_source=file 但未配置 cookies_file 路径")

    elif cookies_source == "browser":
        browser = settings.youtube_browser
        # 使用 yt-dlp 内置的 cookiesfrombrowser
        cookies_opts["cookiesfrombrowser"] = (browser,)
        print(f"[YouTube] 使用浏览器 cookies: {browser}")

    return cookies_opts


def _get_remote_components_opts() -> dict:
    """
    配置 yt-dlp 远程组件，用于生成 PO Token（新版 YouTube 必须）。
    参考：https://github.com/yt-dlp/yt-dlp/wiki/EJS
    ejs:github 从 GitHub 下载挑战脚本，ejs:npm 从 npm 下载。
    """
    settings = get_settings()
    # 可通过 config.yaml 的 youtube.remote_components 控制，默认启用 github
    rc = getattr(settings, 'youtube_remote_components', 'github')
    if not rc or rc.lower() == 'none':
        return {}
    # rc 可以是 "github" / "npm" / "github,npm"
    components = set()
    for c in rc.split(','):
        c = c.strip()
        if c:
            components.add(f"ejs:{c}")
    if components:
        print(f"[YouTube] 启用远程组件: {components}")
        return {"remote_components": components}
    return {}


def _build_ydl_opts(extra: dict = None) -> dict:
    """
    构建通用的 yt-dlp 选项，合并 cookies + JS Runtime + 远程组件配置。
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        **_get_youtube_cookies_opts(),
        **_get_js_runtime_opts(),
        **_get_remote_components_opts(),
    }
    if extra:
        # 允许 extra 覆盖（例如测试时传 quiet=False）
        opts.update(extra)
    return opts


@dataclass
class YouTubeDownloadContext:
    """YouTube 下载的上下文，包含所有共享状态"""
    download_id: str
    url: str
    progress_queue: queue.Queue = field(default_factory=queue.Queue)
    data_queue: queue.Queue = field(default_factory=queue.Queue)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    download_done: threading.Event = field(default_factory=threading.Event)
    file_path: Optional[str] = None
    error: Optional[str] = None
    total_size: int = 0
    total_size_approx: int = 0
    title: str = "video"


# 全局下载上下文管理器
_yt_download_contexts: Dict[str, YouTubeDownloadContext] = {}
_yt_contexts_lock = threading.Lock()


def register_download_context(ctx: YouTubeDownloadContext):
    """注册下载上下文"""
    with _yt_contexts_lock:
        _yt_download_contexts[ctx.download_id] = ctx


def get_download_context(download_id: str) -> Optional[YouTubeDownloadContext]:
    """获取下载上下文"""
    with _yt_contexts_lock:
        return _yt_download_contexts.get(download_id)


def unregister_download_context(download_id: str):
    """注销下载上下文"""
    with _yt_contexts_lock:
        _yt_download_contexts.pop(download_id, None)


class YouTubeExtractor(BaseExtractor):
    """YouTube视频解析器"""

    PLATFORM_NAME = "YouTube"

    def __init__(self):
        pass

    def extract(self, url: str) -> Optional[dict]:
        """从YouTube URL提取视频信息（仅获取元数据，不下载）"""
        opts = _build_ydl_opts({"skip_download": True})

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if not info:
                return None

            # 获取封面
            cover_url = ""
            thumbnails = info.get("thumbnails", []) or []
            if thumbnails:
                best_thumb = max(thumbnails, key=lambda x: x.get("width", 0) if isinstance(x, dict) else 0)
                if isinstance(best_thumb, dict):
                    cover_url = best_thumb.get("url", "")
                else:
                    cover_url = str(best_thumb)

            # 标题
            title = info.get("title", "YouTube_video")
            youtube_id = info.get("id", "")

            result = self.normalize_result({
                "title": title,
                "cover": cover_url,
                "_youtube_id": youtube_id,
            }, self.PLATFORM_NAME)
            result["_needs_ytdl"] = True
            result["_original_url"] = url
            result["_youtube_id"] = youtube_id
            return result

        except Exception as e:
            print(f"YouTube解析失败: {e}")
            return None

    def get_metadata(self, url: str) -> Optional[dict]:
        """
        获取视频元数据（包括文件大小），不下载。
        用于在开始流式下载前预先获取总大小，以便前端设置 Content-Length。
        """
        opts = _build_ydl_opts({
            "skip_download": True,
            "format": "best[ext=mp4]/best",
        })

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if not info:
                return None

            if isinstance(info, list):
                info = info[0]

            filesize = info.get("filesize") or info.get("filesize_approx") or 0
            title = info.get("title", "YouTube_video")

            return {
                "title": title,
                "filesize": filesize,
                "ext": info.get("ext", "mp4"),
            }

        except Exception as e:
            print(f"[!] YouTube元数据获取失败: {e}")
            return None

    def download(self, media_data: dict, save_dir: str = None) -> Optional[Path]:
        """
        用 yt-dlp 直接下载 YouTube 视频到本地。

        Args:
            media_data: extract() 返回的数据（需要包含原始链接或 youtube_id）
            save_dir: 保存目录

        Returns:
            下载文件的 Path，失败返回 None
        """
        if not save_dir:
            return None

        output_dir = Path(save_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        safe_title = re.sub(r'[\\/:*?"<>|]', '_', media_data.get("title", "YouTube_video"))[:80]
        output_template = str(output_dir / f"{safe_title}.%(ext)s")

        opts = _build_ydl_opts({
            "format": "best[ext=mp4]/best",
            "outtmpl": output_template,
        })

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(media_data.get("_original_url") or media_data.get("_url", ""), download=True)

            if not info:
                return None

            expected_filename = f"{safe_title}.mp4"
            downloaded_path = output_dir / expected_filename

            if downloaded_path.exists():
                return downloaded_path

            candidates = list(output_dir.glob(f"{safe_title}*"))
            if candidates:
                return max(candidates, key=lambda p: p.stat().st_mtime)

            return None

        except Exception as e:
            print(f"YouTube下载失败: {e}")
            return None

    def create_download_context(self, url: str, download_id: str) -> YouTubeDownloadContext:
        """
        创建下载上下文，用于管理整个下载生命周期。
        
        Args:
            url: YouTube 视频 URL
            download_id: 唯一标识符，用于 SSE 匹配
            
        Returns:
            YouTubeDownloadContext 对象
        """
        ctx = YouTubeDownloadContext(
            download_id=download_id,
            url=url,
        )
        return ctx

    def start_download(self, ctx: YouTubeDownloadContext):
        """
        启动下载线程（应在后台运行，不阻塞事件循环）。
        
        下载线程会：
        1. 通过 progress_hooks 更新进度到 ctx.progress_queue
        2. 下载完成后将文件路径存入 ctx.file_path
        3. 设置 ctx.download_done 事件
        """
        temp_dir = tempfile.mkdtemp(prefix="yt_stream_")
        safe_title = "youtube_stream"
        output_template = str(Path(temp_dir) / f"{safe_title}.%(ext)s")

        def progress_hook(d: dict):
            """yt-dlp 进度钩子"""
            # 检查取消标志
            if ctx.cancel_event.is_set():
                raise Exception("下载已取消")
            
            if d["status"] == "downloading":
                downloaded = d.get("downloaded_bytes", 0) or 0
                total = d.get("total_bytes") or d.get("total_bytes_approx") or 0
                speed = d.get("speed") or 0
                
                # 优先用 yt-dlp 报告的 total，兜底用元数据预获取的 total_size_approx
                effective_total = total or ctx.total_size_approx
                if effective_total > 0:
                    ctx.total_size = effective_total
                
                progress_pct = (downloaded / effective_total * 100) if effective_total > 0 else 0
                
                ctx.progress_queue.put({
                    "status": "downloading",
                    "downloaded": downloaded,
                    "total": effective_total,
                    "speed": speed,
                    "progress": progress_pct,
                })
            elif d["status"] == "finished":
                downloaded = d.get("downloaded_bytes", 0) or 0
                ctx.progress_queue.put({
                    "status": "finished",
                    "downloaded": downloaded,
                    "total": ctx.total_size or ctx.total_size_approx,
                })

        def download_thread():
            # 立即设置预期路径，让 stream_file 能立即开始读
            # （yt-dlp 会写入同路径的文件）
            ctx.file_path = str(Path(temp_dir) / f"{safe_title}.mp4")
            try:
                opts = _build_ydl_opts({
                    "format": "best[ext=mp4]/best",
                    "outtmpl": output_template,
                    "progress_hooks": [progress_hook],
                })
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(ctx.url, download=True)
                    
                # 下载完成，确认文件路径（若文件名略有不同则更新）
                candidates = list(Path(temp_dir).glob(f"{safe_title}.*"))
                if candidates:
                    ctx.file_path = str(max(candidates, key=lambda p: p.stat().st_mtime))
                    
                # 发送完成信号
                ctx.progress_queue.put({"status": "done"})
                
            except Exception as e:
                ctx.error = str(e)
                ctx.progress_queue.put({"status": "error", "message": str(e)})
            finally:
                ctx.download_done.set()

        # 启动下载线程
        t = threading.Thread(target=download_thread, daemon=True)
        t.start()
        return t

    async def stream_file(self, ctx: YouTubeDownloadContext) -> AsyncIterator[bytes]:
        """
        异步生成器：边下载边推送（小 chunk 分批），不等待下载完成。

        yt-dlp 后台线程写入文件，本生成器轮询文件大小，
        有新数据时分批读取并 yield（每批 ≤ CHUNK_SIZE），
        实现真正的流式传输。
        """
        loop = asyncio.get_event_loop()
        file_size_seen = 0
        CHUNK_SIZE = 512 * 1024  # 512KB per chunk

        def _read_chunk(size_limit: int):
            """在 executor 中读取最多 size_limit 字节"""
            if not ctx.file_path:
                return b""
            path = Path(ctx.file_path)
            if not path.exists():
                return b""
            try:
                with open(path, "rb") as f:
                    f.seek(file_size_seen)
                    return f.read(size_limit)
            except Exception:
                return b""

        print(f"[stream] started, waiting for file... ctx.file_path={ctx.file_path}")
        # 等待文件出现
        while not ctx.file_path or not Path(ctx.file_path).exists():
            await asyncio.sleep(0.05)
        print(f"[stream] file detected: {ctx.file_path}")

        while True:
            await asyncio.sleep(0.05)  # 50ms 轮询间隔（更频繁）

            if not Path(ctx.file_path).exists():
                continue

            current_size = Path(ctx.file_path).stat().st_size

            if current_size > file_size_seen:
                # 读取下一批数据（最多 CHUNK_SIZE）
                read_size = min(CHUNK_SIZE, current_size - file_size_seen)
                chunk = await loop.run_in_executor(None, lambda: _read_chunk(read_size))
                if chunk:
                    file_size_seen += len(chunk)
                    print(f"[stream] yielding {len(chunk)} bytes, sent={file_size_seen}/{current_size}")
                    yield chunk
                    # 立即继续读取（不 sleep），让 chunk 尽快推送
                    continue

            # 没有新数据，检查是否结束
            if ctx.download_done.is_set():
                if file_size_seen >= current_size:
                    print(f"[stream] download done, sent={file_size_seen}, cleaning up")
                    break
                await asyncio.sleep(0.1)

        # 清理临时文件
        if ctx.file_path:
            temp_dir = str(Path(ctx.file_path).parent)
            print(f"[stream] cleanup: {temp_dir}")
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
        print("[stream] done")


# 全局实例
_yt_extractor: Optional[YouTubeExtractor] = None


def get_youtube_extractor() -> YouTubeExtractor:
    """获取 YouTube 提取器实例（单例）"""
    global _yt_extractor
    if _yt_extractor is None:
        _yt_extractor = YouTubeExtractor()
    return _yt_extractor
