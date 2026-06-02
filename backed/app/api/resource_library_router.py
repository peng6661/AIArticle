from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import ResourceLibraryItemModel

router = APIRouter(prefix="/api/resource-library", tags=["资料库"])


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Invalid datetime: {value}")


def _format_datetime(value: datetime | None) -> str:
    if not value:
        return ""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _serialize(item: ResourceLibraryItemModel) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "netdiskType": item.netdisk_type,
        "url": item.url,
        "feishuTableName": item.feishu_table_name,
        "createdAt": _format_datetime(item.source_created_at),
        "updatedAt": _format_datetime(item.source_updated_at),
    }


class ResourceItemPayload(BaseModel):
    id: int | None = Field(default=None, ge=1)
    name: str = Field(..., min_length=1, max_length=512)
    netdiskType: str = Field("", max_length=64)
    url: str = Field(..., min_length=1)
    feishuTableName: str = Field("", max_length=128)
    createdAt: str = ""
    updatedAt: str = ""


@router.get("")
def list_resources(
    keyword: str = Query("", max_length=200),
    netdiskType: str = Query("", max_length=64),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(ResourceLibraryItemModel)
    count_stmt = select(func.count()).select_from(ResourceLibraryItemModel)
    conditions = []

    if keyword.strip():
        pattern = f"%{keyword.strip()}%"
        conditions.append(
            or_(
                ResourceLibraryItemModel.name.like(pattern),
                ResourceLibraryItemModel.url.like(pattern),
                ResourceLibraryItemModel.feishu_table_name.like(pattern),
            )
        )
    if netdiskType.strip():
        conditions.append(ResourceLibraryItemModel.netdisk_type == netdiskType.strip())

    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = db.scalar(count_stmt) or 0
    items = db.scalars(
        stmt.order_by(
            ResourceLibraryItemModel.source_updated_at.desc(),
            ResourceLibraryItemModel.id.desc(),
        )
        .offset((page - 1) * pageSize)
        .limit(pageSize)
    ).all()

    return {
        "success": True,
        "data": [_serialize(item) for item in items],
        "pagination": {
            "page": page,
            "pageSize": pageSize,
            "total": total,
            "totalPages": (total + pageSize - 1) // pageSize if total else 0,
        },
    }


@router.get("/netdisk-types")
def list_netdisk_types(db: Session = Depends(get_db)):
    rows = db.execute(
        select(ResourceLibraryItemModel.netdisk_type, func.count())
        .where(ResourceLibraryItemModel.netdisk_type != "")
        .group_by(ResourceLibraryItemModel.netdisk_type)
        .order_by(func.count().desc(), ResourceLibraryItemModel.netdisk_type.asc())
    ).all()
    return {
        "success": True,
        "data": [{"name": name, "count": count} for name, count in rows],
    }


@router.post("")
def create_resource(payload: ResourceItemPayload, db: Session = Depends(get_db)):
    if payload.id is not None and db.get(ResourceLibraryItemModel, payload.id):
        raise HTTPException(status_code=409, detail="资源 ID 已存在")

    next_id = payload.id
    if next_id is None:
        next_id = min(db.scalar(select(func.min(ResourceLibraryItemModel.id))) or 0, 0) - 1

    item = ResourceLibraryItemModel(
        id=next_id,
        name=payload.name.strip(),
        netdisk_type=payload.netdiskType.strip(),
        url=payload.url.strip(),
        feishu_table_name=payload.feishuTableName.strip(),
        source_created_at=_parse_datetime(payload.createdAt),
        source_updated_at=_parse_datetime(payload.updatedAt),
    )
    db.add(item)
    db.flush()
    return {"success": True, "data": _serialize(item)}


@router.put("/{resource_id}")
def update_resource(resource_id: int, payload: ResourceItemPayload, db: Session = Depends(get_db)):
    item = db.get(ResourceLibraryItemModel, resource_id)
    if not item:
        raise HTTPException(status_code=404, detail="资源不存在")

    item.name = payload.name.strip()
    item.netdisk_type = payload.netdiskType.strip()
    item.url = payload.url.strip()
    item.feishu_table_name = payload.feishuTableName.strip()
    item.source_created_at = _parse_datetime(payload.createdAt)
    item.source_updated_at = _parse_datetime(payload.updatedAt)
    db.flush()
    return {"success": True, "data": _serialize(item)}


@router.delete("/{resource_id}")
def delete_resource(resource_id: int, db: Session = Depends(get_db)):
    item = db.get(ResourceLibraryItemModel, resource_id)
    if not item:
        raise HTTPException(status_code=404, detail="资源不存在")
    db.delete(item)
    return {"success": True, "message": "资源已删除"}
