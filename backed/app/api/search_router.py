"""
多平台视频搜索 API 路由
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.video_search_service import (
    search_all,
    ALL_PLATFORMS,
    PLATFORM_FETCHERS,
)

router = APIRouter(prefix="/api/video", tags=["视频搜索"])


class SearchRequest(BaseModel):
    keyword: str = Field(..., min_length=1, description="搜索关键词")
    platforms: list[str] = Field(
        default_factory=lambda: ALL_PLATFORMS,
        description="目标平台列表，默认全部",
    )
    limit: int = Field(10, ge=1, le=30, description="每平台返回数量")


@router.get("/platforms", summary="获取支持的平台列表")
def list_platforms():
    return {
        "success": True,
        "platforms": [
            {"id": pid, "name": name}
            for pid, (name, _) in PLATFORM_FETCHERS.items()
        ],
    }


@router.post("/search", summary="多平台视频搜索")
async def search_videos(req: SearchRequest):
    """
    按关键词并发搜索多个视频平台，返回标准化结果。
    失败的平台不会阻塞其他平台，错误信息在 errors 字段中返回。
    """
    # 校验平台 ID
    invalid = [p for p in req.platforms if p not in PLATFORM_FETCHERS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {', '.join(invalid)}")

    try:
        results, errors = await search_all(
            keyword=req.keyword,
            platforms=req.platforms,
            limit=req.limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"搜索失败: {exc}")

    return {
        "success": True,
        "keyword": req.keyword,
        "results": results,
        "errors": errors,
    }
