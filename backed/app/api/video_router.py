"""
视频解析API路由
整合自下载平台-server，对接前端下载页面
"""
import os
import uuid
import threading
import httpx
from typing import Optional, Dict
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from urllib.parse import urlparse, unquote, quote
from app.services.video_parser import video_parser
from app.services.youtube_download_service import (
    get_youtube_extractor,
    YouTubeDownloadContext,
)
from app.core.config import get_settings

# ── YouTube 下载上下文管理（用于取消功能）────────────────────────────
_yt_download_contexts: Dict[str, YouTubeDownloadContext] = {}
_yt_contexts_lock = threading.Lock()


def _register_yt_context(ctx: YouTubeDownloadContext):
    """注册 YouTube 下载上下文"""
    with _yt_contexts_lock:
        _yt_download_contexts[ctx.download_id] = ctx


def _get_yt_context(download_id: str) -> Optional[YouTubeDownloadContext]:
    """获取 YouTube 下载上下文"""
    with _yt_contexts_lock:
        return _yt_download_contexts.get(download_id)


def _unregister_yt_context(download_id: str):
    """注销 YouTube 下载上下文"""
    with _yt_contexts_lock:
        _yt_download_contexts.pop(download_id, None)

# 临时文件存储目录（用于兼容性，当前主要使用流式转发）
TEMP_DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "temp_downloads")
os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)

cfg = get_settings()

# ── 各平台常用 UA 轮换池 ──────────────────────────────────────────
_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
_IOS_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)
# 抖音专用 - 使用更真实的浏览器头组合
_DOUYIN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0"
)

_PLATFORM_UA = {
    "douyin":   _DOUYIN_UA,  # 抖音专用
    "tiktok":   _DESKTOP_UA,
    "bilibili": _DESKTOP_UA,
    "instagram": _MOBILE_UA,
    "kuaishou": _MOBILE_UA,
    "x":        _DESKTOP_UA,
    "youtube":  _DESKTOP_UA,
}

_PLATFORM_REFERER = {
    "douyin":   "https://www.douyin.com/",
    "tiktok":   "https://www.tiktok.com/",
    "bilibili": "https://www.bilibili.com/",
    "instagram":"https://www.instagram.com/",
    "kuaishou": "https://www.kuaishou.com/",
    "x":        "https://x.com/",
    "youtube":  "https://www.youtube.com/",
}

router = APIRouter(prefix="/api/video", tags=["视频解析下载（全平台）"])


class ParseRequest(BaseModel):
    """解析请求"""
    url: str


class ParseResponse(BaseModel):
    """解析响应"""
    success: bool
    message: str = ""
    data: Optional[dict] = None


@router.post("/parse", response_model=ParseResponse, summary="解析视频链接（支持全平台）")
async def parse_video(request: ParseRequest):
    """
    统一解析视频/图片链接，自动识别平台。

    **支持平台：**
    抖音 / 哔哩哔哩(B站) / TikTok / 快手 / Instagram / X(Twitter) / YouTube

    **返回数据结构：**
    - video_url: 视频直链（视频帖子；YouTube 除外，需走专用下载接口）
    - cover_url: 封面图 URL
    - images: 多图列表（Instagram 轮播帖）
    - platform: 识别的平台名
    - media_type: video / image
    """
    if not request.url:
        raise HTTPException(status_code=400, detail="URL不能为空")

    result = video_parser.parse(request.url)

    if result:
        # 检查是否是视频失效的特殊返回
        if result.get("error_type") == "blocked":
            return ParseResponse(
                success=False,
                message=result.get("error", "视频已失效或无法访问"),
                data=None
            )

        # 区分图片和视频
        video_url = result.get("video_url", "")
        cover_url = result.get("cover_url", "")
        media_type = "video" if video_url else "image"

        # 如果是图片，使用cover_url作为image_url
        image_url = cover_url if not video_url else ""

        # 获取多图列表（Instagram轮播帖子）
        images_list = result.get("images", [])

        # YouTube / X 特殊处理
        is_youtube = result.get("platform") == "youtube"
        is_x = result.get("platform") == "x"
        is_no_media = result.get("_no_media", False)
        has_direct_url = bool(result.get("video_url", "") and result.get("video_url", "") != "yt-dlp-stream")

        # X 推文存在但无可下载媒体内容（纯文字/卡片推文）
        if is_x and is_no_media:
            return ParseResponse(
                success=False,
                message=f"该推文没有视频或图片内容（{result.get('title', '纯文字推文')}）",
                data={
                    "title": result.get("title", ""),
                    "platform": "x",
                    "media_type": "text",
                    "_no_media": True,
                }
            )

        if is_youtube:
            # YouTube 仍需要 yt-dlp（CDN 直链会过期）
            media_type = "video"
            video_url = "yt-dlp-stream"
        elif is_x and has_direct_url:
            # X 有 CDN 直链，可以直接下载
            media_type = result.get("media_type", "video")
            video_url = result.get("video_url", "")
        elif is_x:
            # X 无直链接但可能有媒体（走 yt-dlp 回退）
            media_type = "video"
            video_url = "yt-dlp-stream"

        return ParseResponse(
            success=True,
            message="解析成功",
            data={
                "title": result.get("title", ""),
                "video_url": video_url,
                "cover_url": cover_url,
                "image_url": image_url,
                "platform": result.get("platform", ""),
                "media_type": media_type,
                "images": images_list,  # 多图列表
                "image_count": len(images_list),  # 图片数量
                "_original_url": request.url if (is_youtube or is_x) else "",  # 原始链接（用于 yt-dlp）
                "_needs_ytdl": is_youtube or is_x,  # 标记是否需要 yt-dlp
            }
        )
    else:
        return ParseResponse(
            success=False,
            message="暂不支持该链接或解析失败",
            data=None
        )


@router.get("/parse", summary="GET方式解析视频链接（支持全平台）")
async def parse_video_get(url: str):
    """GET方式解析视频/图片链接，自动识别平台（支持抖音/B站/TikTok/快手/Instagram/X/YouTube）"""
    if not url:
        raise HTTPException(status_code=400, detail="URL不能为空")

    result = video_parser.parse(url)

    if result:
        # 检查是否是视频失效的特殊返回
        if result.get("error_type") == "blocked":
            return {
                "success": False,
                "message": result.get("error", "视频已失效或无法访问"),
                "data": None
            }

        video_url = result.get("video_url", "")
        cover_url = result.get("cover_url", "")
        media_type = "video" if video_url else "image"
        image_url = cover_url if not video_url else ""
        images_list = result.get("images", [])

        return {
            "success": True,
            "message": "解析成功",
            "data": {
                "title": result.get("title", ""),
                "video_url": video_url,
                "cover_url": cover_url,
                "image_url": image_url,
                "platform": result.get("platform", ""),
                "media_type": media_type,
                "images": images_list,
                "image_count": len(images_list),
            }
        }
    else:
        return {
            "success": False,
            "message": "暂不支持该链接或解析失败",
            "data": None
        }


@router.get("/platforms", summary="获取支持的平台列表")
async def get_platforms():
    """返回所有支持的视频/图片解析下载平台列表"""
    return {
        "platforms": [
            {"id": "douyin", "name": "抖音"},
            {"id": "bilibili", "name": "哔哩哔哩"},
            {"id": "tiktok", "name": "TikTok"},
            {"id": "kuaishou", "name": "快手"},
            {"id": "instagram", "name": "Instagram"},
            {"id": "x", "name": "X"},
            {"id": "youtube", "name": "YouTube"},
        ]
    }


def build_download_headers(platform: str, url: str = "") -> dict:
    """构建各平台下载请求头（含 Range 头避免 403）"""

    ua = _PLATFORM_UA.get(platform, _DESKTOP_UA)
    referer = _PLATFORM_REFERER.get(platform, "https://www.douyin.com/")

    headers = {
        "User-Agent": ua,
        "Referer": referer,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        # 移除 identity 编码（会暴露爬虫），让服务器决定压缩方式
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        # Range 头是关键：抖音 CDN 没有它会返回 403
        "Range": "bytes=0-",
        # 额外请求头，让CDN认为是正常浏览器访问
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
    }

    # 从 URL 中提取 Host
    if url:
        parsed = urlparse(url)
        if parsed.netloc:
            headers["Host"] = parsed.netloc

    return headers


def _build_preview_headers(platform: str, url: str = "") -> dict:
    """构建预览/封面图请求头（针对不同平台优化）"""

    if platform == "douyin":
        # 抖音封面图 - 简化的请求头
        headers = {
            "User-Agent": cfg.douyin_user_agent,
            "Referer": "https://www.douyin.com/",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            # 不使用压缩，让图片原始传输
            "Accept-Encoding": "identity",
        }
    elif platform == "tiktok":
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
            "Referer": "https://www.tiktok.com/",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "identity",
        }
    else:
        # 其他平台使用默认headers
        headers = build_download_headers(platform, url)
        # 移除 Range 头（图片不需要）
        headers.pop("Range", None)

    # 从 URL 中提取 Host
    if url:
        parsed = urlparse(url)
        if parsed.netloc:
            headers["Host"] = parsed.netloc

    return headers


class DownloadError(Exception):
    """下载异常，可安全地在流式响应中处理"""
    pass


async def _probe_url_accessible(url: str, headers: dict, timeout: int) -> tuple[bool, str]:
    """
    探测URL是否可访问（发HEAD请求）
    返回 (可访问, 错误信息)
    """
    try:
        async with httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
            timeout=httpx.Timeout(timeout),
        ) as client:
            response = await client.head(url)
            status = response.status_code
            print(f"[*] HEAD探测状态码: {status}")

            if status == 403:
                return False, "视频链接已过期或无效，请重新在抖音APP中复制视频链接后重试"
            if status not in (200, 206):
                return False, f"下载失败，服务器返回状态码: {status}"
            return True, ""
    except httpx.TimeoutException:
        return False, "探测超时，请检查网络后重试"
    except httpx.HTTPError as e:
        return False, f"探测异常: {str(e)}"
    except Exception as e:
        return False, f"未知错误: {str(e)}"


async def generate_video_stream(url: str, headers: dict, timeout: int, platform: str = "douyin"):
    """
    异步流式获取视频数据（httpx）
    边下载边 yield，不占用服务器内存
    """
    print(f"[*] 开始流式下载: {url[:80]}...")
    print(f"[*] 请求头: UA={headers.get('User-Agent', '')[:60]}...")

    try:
        async with httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
            timeout=httpx.Timeout(timeout),
        ) as client:
            async with client.stream("GET", url) as response:
                status = response.status_code
                print(f"[*] 响应状态码: {status}")

                if status == 403:
                    print("[!] 403 Forbidden，CDN 拒绝了请求")
                    return

                if status not in (200, 206):
                    print(f"[!] 非正常状态码: {status}")
                    return

                total_size = 0
                async for chunk in response.aiter_bytes(chunk_size=524288):  # 512KB
                    if chunk:
                        total_size += len(chunk)
                        yield chunk

                print(f"[*] 流式转发完成，总大小: {total_size / 1024 / 1024:.2f} MB")

    except httpx.TimeoutException:
        print("[!] 流式下载超时")
    except httpx.HTTPError as e:
        print(f"[!] 流式下载异常: {e}")


def _get_image_ext(url: str) -> str:
    """从URL获取图片扩展名"""
    if ".jpg" in url.lower() or ".jpeg" in url.lower():
        return "jpg"
    elif ".png" in url.lower():
        return "png"
    elif ".webp" in url.lower():
        return "webp"
    elif ".gif" in url.lower():
        return "gif"
    return "jpg"


@router.get("/preview", summary="图片预览代理（支持全平台）")
async def preview_image(url: str, platform: str = "douyin"):
    """
    图片预览代理（解决跨域问题）。
    通过本服务转发远程图片到前端，自动根据平台构建对应请求头。

    **platform 参数：** douyin / bilibili / tiktok / kuaishou / instagram / x / youtube
    """
    if not url:
        raise HTTPException(status_code=400, detail="URL不能为空")

    decoded_url = url

    # 为不同平台构建特定请求头
    headers = _build_preview_headers(platform, decoded_url)

    ext = _get_image_ext(decoded_url)
    resp_headers = {
        "Content-Type": f"image/{ext}",
        "Cache-Control": "max-age=3600",
    }

    # 图片直接获取
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(cfg.douyin_timeout_download)) as client:
            resp = await client.get(decoded_url, headers=headers, follow_redirects=True)

            if resp.status_code == 403:
                raise HTTPException(status_code=403, detail="图片链接已过期或无效")
            if resp.status_code not in (200, 206):
                raise HTTPException(status_code=502, detail=f"获取图片失败，状态码: {resp.status_code}")

            return Response(
                content=resp.content,
                media_type=f"image/{ext}",
                headers=resp_headers,
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="获取图片超时")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"获取图片失败: {str(e)}")


@router.get("/download", summary="流式下载视频/图片（支持全平台）")
async def download_video(url: str, platform: str = "douyin", media_type: str = "video", download_id: str = ""):
    """
    流式代理下载视频或图片，边下载边转发，不占用服务器内存，适合大文件。
    
    **platform 参数：** douyin / bilibili / tiktok / kuaishou / instagram / x / youtube
    **media_type 参数：** video（默认） / image
    
    **YouTube 特殊处理：** 当 platform=youtube 时，url 应为 YouTube 原始链接，
    接口会通过 yt-dlp 实时拉取视频并流式转发给前端。
    """
    if not url:
        raise HTTPException(status_code=400, detail="URL不能为空")

    decoded_url = unquote(url)

    # ── YouTube 特殊处理：走 yt-dlp 流式下载 ──
    if platform == "youtube":
        # 获取 YouTube 提取器实例
        yt_extractor = get_youtube_extractor()

        # 先获取元数据（含文件大小）
        total_size = 0
        title = "video"
        try:
            meta = yt_extractor.get_metadata(decoded_url)
            if meta:
                total_size = meta.get("filesize", 0) or meta.get("filesize_approx", 0) or 0
                title = meta.get("title", "video")
        except Exception as e:
            print(f"[!] YouTube元数据预获取失败: {e}")

        # 创建下载上下文
        download_id = download_id or uuid.uuid4().hex
        ctx = yt_extractor.create_download_context(decoded_url, download_id)
        ctx.total_size_approx = total_size
        ctx.title = title

        # 注册上下文（用于取消）
        _register_yt_context(ctx)

        # 启动后台下载线程
        yt_extractor.start_download(ctx)

        # 异步生成器：流式返回视频数据
        async def yt_stream_generator():
            try:
                async for chunk in yt_extractor.stream_file(ctx):
                    yield chunk
            except Exception as e:
                print(f"[!] YouTube流式下载异常: {e}")
            finally:
                _unregister_yt_context(download_id)

        # 构建响应头（文件名使用 RFC 5987 编码避免中文乱码）
        safe_title = quote(title, safe="")
        resp_headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_title}.mp4",
            "Content-Type": "video/mp4",
            "Cache-Control": "no-cache",
        }
        if total_size > 0:
            resp_headers["Content-Length"] = str(total_size)

        return StreamingResponse(
            yt_stream_generator(),
            headers=resp_headers,
        )

    # ── X/Twitter 特殊处理：优先 CDN 直链，回退 yt-dlp ──
    if platform == "x":
        from app.services.x_download_service import XVideoExtractor

        x_extractor = XVideoExtractor()

        def x_stream_generator():
            try:
                # stream_to_iterator 内部自动判断：
                # 1. 如果 media_data 有 video_url 直链 → 直接从 CDN 流式转发
                # 2. 如果没有直链 → 回退到 yt-dlp
                for chunk in x_extractor.stream_to_iterator(decoded_url):
                    yield chunk
            except Exception as e:
                print(f"[!] X/Twitter流式下载异常: {e}")

        resp_headers = {
            "Content-Disposition": 'attachment; filename="x_media.mp4"',
            "Content-Type": "video/mp4",
            "Cache-Control": "no-cache",
        }
        return StreamingResponse(
            x_stream_generator(),
            headers=resp_headers,
        )

    headers = build_download_headers(platform, decoded_url)

    if media_type == "image":
        ext = _get_image_ext(decoded_url)
        resp_headers = {
            "Content-Disposition": f'attachment; filename="image.{ext}"',
            "Content-Type": f"image/{ext}",
            "Cache-Control": "no-cache",
        }
    else:
        resp_headers = {
            "Content-Disposition": 'attachment; filename="video.mp4"',
            "Content-Type": "video/mp4",
            "Cache-Control": "no-cache",
        }

    return StreamingResponse(
        generate_video_stream(decoded_url, headers, cfg.douyin_timeout_download, platform),
        headers=resp_headers,
    )


@router.get("/youtube-metadata", summary="获取YouTube视频元数据（含文件大小）")
async def get_youtube_metadata(url: str):
    """
    在开始 YouTube 流式下载前，先获取视频元数据（含预估文件大小），
    用于前端设置进度条的总量。
    """
    if not url:
        raise HTTPException(status_code=400, detail="URL不能为空")

    decoded_url = unquote(url)
    from app.services.youtube_download_service import YouTubeExtractor

    yt_extractor = YouTubeExtractor()
    metadata = yt_extractor.get_metadata(decoded_url)

    if not metadata:
        raise HTTPException(status_code=502, detail="无法获取YouTube视频元数据")

    return {
        "success": True,
        "title": metadata.get("title", ""),
        "filesize": metadata.get("filesize", 0),
        "ext": metadata.get("ext", "mp4"),
    }


@router.post("/youtube-cancel", summary="取消YouTube下载")
async def cancel_youtube_download(download_id: str):
    """
    取消指定的 YouTube 下载任务。

    设置 cancel_event 标志，yt-dlp 进度钩子会检测到并抛出异常终止下载。
    """
    ctx = _get_yt_context(download_id)
    if not ctx:
        return {"success": True, "message": "任务不存在或已结束"}

    # 设置取消标志
    ctx.cancel_event.set()

    # 清理上下文
    _unregister_yt_context(download_id)

    return {"success": True, "message": "取消成功"}








