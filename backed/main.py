"""
AIcreator FastAPI 主入口
抖音视频 → 提取音频 → 语音转写 → 生成文章 → 生成配图 → 微信公众号发布
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import urllib.parse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse

from app.core.config import get_settings
from app.api.pipeline_router import router as step_router
from app.api.full_pipeline_router import router as full_router
from app.api.video_router import router as video_router
from app.api.hot_router import router as hot_router
from app.api.knowledge_router import router as knowledge_router
from app.api.search_router import router as search_router
from app.db.database import ensure_database_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    # 确保目录存在
    cfg.downloads_dir.mkdir(parents=True, exist_ok=True)
    cfg.outputs_dir.mkdir(parents=True, exist_ok=True)
    ensure_database_schema()
    print(f"✅ AIcreator 启动完成")
    print(f"   下载目录: {cfg.downloads_dir.resolve()}")
    print(f"   输出目录: {cfg.outputs_dir.resolve()}")
    yield
    print("👋 AIcreator 已关闭")


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(
        title=cfg.server_title,
        description=cfg.server_description,
        version=cfg.server_version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(step_router)
    app.include_router(full_router)
    # video_router 自身已定义 prefix="/api/video"，此处不再重复添加
    app.include_router(video_router)
    app.include_router(search_router)
    app.include_router(hot_router)
    app.include_router(knowledge_router)

    @app.get("/", tags=["Root"])
    def root():
        return {
            "name": cfg.server_title,
            "version": cfg.server_version,
            "description": cfg.server_description,
            "docs": "/docs",
            "pipeline_steps": [
                "POST /pipeline/run              → 一键全流程（支持全平台）",
                "POST /pipeline/step/download    → Step1: 下载视频（支持抖音/Instagram/B站/TikTok/快手/X/YouTube）",
                "POST /pipeline/step/extract_audio → Step2: 提取音频",
                "POST /pipeline/step/transcribe  → Step3: 语音转写",
                "POST /pipeline/step/convert_html → Step6: 微信 HTML 清洗",
                "POST /pipeline/step/publish_draft → Step7: 发布微信草稿",
                "GET  /pipeline/jobs/{job_id}    → 查询进度",
            ],
            "video_api": [
                "POST   /api/video/parse         → 解析链接（自动识别平台）",
                "GET    /api/video/parse         → GET方式解析",
                "GET    /api/video/download      → 流式下载视频/图片",
                "GET    /api/video/preview       → 图片预览代理",
                "GET    /api/video/platforms     → 支持平台列表",
                "POST   /api/video/search        → 多平台视频搜索",
                "GET    /api/video/search/platforms → 搜索支持的平台",
            ],
            "hot_api": [
                "GET    /api/hot/boards         → 获取热搜榜单聚合",
            ],
            "knowledge_api": [
                "POST   /api/knowledge/collections       → 创建知识库集合",
                "GET    /api/knowledge/collections       → 列出所有集合",
                "DELETE /api/knowledge/collections/{id}  → 删除集合",
                "POST   /api/knowledge/documents/text    → 上传文本/Markdown 文档",
                "POST   /api/knowledge/documents/pdf     → 上传 PDF 文件",
                "POST   /api/knowledge/documents/from-job → 从 pipeline 任务导入",
                "GET    /api/knowledge/documents         → 列出文档",
                "DELETE /api/knowledge/documents/{id}    → 删除文档",
                "POST   /api/knowledge/search            → 测试检索",
            ],
        }

    @app.get("/health", tags=["Root"])
    def health():
        return {"status": "ok"}

    @app.get("/api/serve-file", tags=["File"])
    async def serve_file(path: str):
        """
        提供本地文件服务，用于前端预览和下载。
        视频文件使用 StreamingResponse + 明确 Content-Length，确保前端进度条能正常工作。
        图片等小文件仍使用 FileResponse。
        """
        try:
            # 解码 URL 编码的路径
            file_path = Path(urllib.parse.unquote(path))
            
            # 安全检查：确保文件存在且在允许的目录下
            downloads_dir = get_settings().downloads_dir.resolve()
            outputs_dir = get_settings().outputs_dir.resolve()
            
            resolved_path = file_path.resolve()
            
            # 允许访问 downloads 和 outputs 目录下的文件
            allowed_dirs = [downloads_dir, outputs_dir]
            if not any(str(resolved_path).startswith(str(d)) for d in allowed_dirs):
                raise HTTPException(status_code=403, detail="不允许访问该目录")
            
            if not resolved_path.exists():
                raise HTTPException(status_code=404, detail="文件不存在")
            
            suffix = resolved_path.suffix.lower()

            # 图片直接用 FileResponse（小文件，无需进度）
            if suffix in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
                return FileResponse(resolved_path, media_type=f"image/{suffix.lstrip('.')}")

            # 视频 / 音频：StreamingResponse + 显式 Content-Length
            # FileResponse 在某些 ASGI 中间件下会被 Transfer-Encoding: chunked 覆盖掉
            # Content-Length，导致 Next.js 代理层拿不到大小，前端无法显示真实进度。
            CHUNK = 1024 * 512  # 512 KB / chunk
            file_size = resolved_path.stat().st_size

            media_type_map = {
                ".mp4":  "video/mp4",
                ".mp3":  "audio/mpeg",
                ".wav":  "audio/wav",
                ".m4a":  "audio/mp4",
                ".webm": "video/webm",
                ".mov":  "video/quicktime",
            }
            media_type = media_type_map.get(suffix, "application/octet-stream")

            async def file_streamer():
                with open(resolved_path, "rb") as f:
                    while True:
                        chunk = f.read(CHUNK)
                        if not chunk:
                            break
                        yield chunk

            return StreamingResponse(
                file_streamer(),
                media_type=media_type,
                headers={
                    "Content-Length": str(file_size),
                    "Content-Disposition": f'attachment; filename="{resolved_path.name}"',
                    "Cache-Control": "public, max-age=3600",
                },
            )
                
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"读取文件失败: {str(e)}")

    @app.get("/api/video-info", tags=["File"])
    async def get_video_info(path: str):
        """
        获取本地视频文件的信息（大小），用于前端判断是否需要显示大文件警告。
        返回 JSON: {"size": int, "size_mb": float}
        """
        try:
            file_path = Path(urllib.parse.unquote(path))
            downloads_dir = get_settings().downloads_dir.resolve()
            outputs_dir = get_settings().outputs_dir.resolve()
            resolved_path = file_path.resolve()
            
            allowed_dirs = [downloads_dir, outputs_dir]
            if not any(str(resolved_path).startswith(str(d)) for d in allowed_dirs):
                raise HTTPException(status_code=403, detail="不允许访问该目录")
            
            if not resolved_path.exists():
                raise HTTPException(status_code=404, detail="文件不存在")
            
            size = resolved_path.stat().st_size
            return {"size": size, "size_mb": round(size / (1024 * 1024), 2)}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"获取文件信息失败: {str(e)}")

    @app.get("/api/stream-video", tags=["File"])
    async def stream_video(url: str):
        """
        流式代理远程视频，支持 Content-Length 透传（前端口可以看到真实进度）。
        用于需要边下边播或显示下载进度的场景。
        chunk_size = 1MB，平衡性能和首帧响应速度。
        """
        import httpx
        
        try:
            # 解码 URL
            video_url = urllib.parse.unquote(url)
            
            # 先用 HEAD 请求获取文件大小
            async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
                head_resp = await client.head(video_url)
                content_length = head_resp.headers.get("content-length")
                content_type = head_resp.headers.get("content-type", "video/mp4")
                
                if content_length:
                    total_size = int(content_length)
                else:
                    total_size = 0
                
                # 流式请求视频内容，chunk_size = 1MB
                async def video_generator():
                    CHUNK_SIZE = 1024 * 1024  # 1MB
                    async with client.stream("GET", video_url) as stream_resp:
                        stream_resp.raise_for_status()
                        async for chunk in stream_resp.aiter_bytes(chunk_size=CHUNK_SIZE):
                            if chunk:
                                yield chunk
                
                # 构建响应头
                headers = {
                    "Content-Type": content_type,
                    "Accept-Ranges": "bytes",
                }
                if total_size > 0:
                    headers["Content-Length"] = str(total_size)
                
                return StreamingResponse(
                    video_generator(),
                    headers=headers,
                    media_type=content_type,
                )
                
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=f"视频请求失败: {str(e)}")
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"视频请求错误: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"流式传输失败: {str(e)}")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    cfg = get_settings()
    uvicorn.run(
        "main:app",
        host=cfg.server_host,
        port=cfg.server_port,
        reload=True,
    )
