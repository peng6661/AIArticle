"""
热搜聚合 API
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.hot_service import fetch_hot_boards


router = APIRouter(prefix="/api/hot", tags=["热搜聚合"])


@router.get("/boards", summary="获取热搜榜单")
def get_hot_boards(force_refresh: bool = Query(False, description="是否强制刷新缓存")):
    try:
        boards, errors = fetch_hot_boards(force_refresh=force_refresh)
        message = "获取成功"
        if errors:
            message = f"部分榜单获取失败: {'; '.join(errors)}"
        return {
            "success": True,
            "message": message,
            "boards": boards,
            "errors": errors,
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"热搜抓取失败: {exc}")
