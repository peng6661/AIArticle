"""
知识库管理 API 路由
提供集合和文档的 CRUD 操作，以及 RAG 检索测试。
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.rag.rag_service import rag_service

router = APIRouter(prefix="/api/knowledge", tags=["知识库"])


# ── 请求/响应模型 ────────────────────────────────────────────────────────────

class CreateCollectionRequest(BaseModel):
    name: str = Field(..., description="集合名称（唯一标识）", min_length=1, max_length=128)
    description: str = Field("", description="集合描述")


class CollectionResponse(BaseModel):
    success: bool
    message: str = ""
    data: dict[str, Any] | None = None


class IngestTextRequest(BaseModel):
    collection_name: str = Field(..., description="集合名称")
    content: str = Field(..., description="文本内容", min_length=1)
    title: str = Field("", description="文档标题，默认自动生成")
    source_type: str = Field("text", description="来源类型：text / markdown")
    api_key: str = Field(..., description="API Key")
    embedding_model: str = Field("", description="向量模型名，留空使用 config 默认值")
    embedding_provider: str = Field("", description="向量模型服务商: siliconflow | zhipu，留空使用 config 默认值")


class IngestFromJobRequest(BaseModel):
    collection_name: str = Field(..., description="集合名称")
    job_id: str = Field(..., description="Pipeline 任务 ID")
    api_key: str = Field(..., description="API Key")
    embedding_model: str = Field("", description="向量模型名，留空使用 config 默认值")
    embedding_provider: str = Field("", description="向量模型服务商: siliconflow | zhipu，留空使用 config 默认值")


class SearchRequest(BaseModel):
    collection_name: str = Field(..., description="集合名称")
    query: str = Field(..., description="查询文本", min_length=1)
    api_key: str = Field(..., description="API Key")
    top_k: int = Field(5, description="返回的最大结果数", ge=1, le=20)
    embedding_model: str = Field("", description="向量模型名，留空使用 config 默认值")
    embedding_provider: str = Field("", description="向量模型服务商: siliconflow | zhipu，留空使用 config 默认值")


# ── 集合管理 ────────────────────────────────────────────────────────────────

@router.post("/collections", response_model=CollectionResponse)
def create_collection(req: CreateCollectionRequest):
    """创建知识库集合。"""
    try:
        result = rag_service.create_collection(req.name, req.description)
        return CollectionResponse(success=True, message="集合创建成功", data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建集合失败: {e}")


@router.get("/collections", response_model=CollectionResponse)
def list_collections():
    """列出所有知识库集合。"""
    try:
        collections = rag_service.list_collections()
        return CollectionResponse(
            success=True,
            data={"collections": collections, "total": len(collections)},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取集合列表失败: {e}")


@router.delete("/collections/{collection_id}", response_model=CollectionResponse)
def delete_collection(collection_id: int):
    """删除知识库集合及其所有数据。"""
    try:
        success = rag_service.delete_collection(collection_id)
        if not success:
            raise HTTPException(status_code=404, detail="集合不存在")
        return CollectionResponse(success=True, message="集合已删除")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除集合失败: {e}")


# ── 文档管理 ────────────────────────────────────────────────────────────────

@router.post("/documents/text", response_model=CollectionResponse)
def ingest_text(req: IngestTextRequest):
    """上传文本/Markdown 文档到知识库。"""
    try:
        title = req.title or req.content[:50].replace("\n", " ") + "..."
        result = rag_service.ingest_text(
            collection_name=req.collection_name,
            content=req.content,
            title=title,
            source_type=req.source_type,
            api_key=req.api_key,
            embedding_model=req.embedding_model or None,
            embedding_provider=req.embedding_provider or None,
        )
        return CollectionResponse(success=True, message="文档入库成功", data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文档入库失败: {e}")


@router.post("/documents/pdf", response_model=CollectionResponse)
async def ingest_pdf(
    collection_name: str = Form(..., description="集合名称"),
    api_key: str = Form(..., description="API Key"),
    title: str = Form("", description="文档标题"),
    embedding_model: str = Form("", description="向量模型名，留空使用 config 默认值"),
    embedding_provider: str = Form("", description="向量模型服务商: siliconflow | zhipu，留空使用 config 默认值"),
    file: UploadFile = File(..., description="PDF 文件"),
):
    """上传 PDF 文件到知识库。"""
    cfg = get_settings()

    # 保存上传的文件
    upload_dir = cfg.downloads_dir / "knowledge_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_ext = Path(file.filename or "document.pdf").suffix or ".pdf"
    saved_path = upload_dir / f"{uuid.uuid4().hex}{file_ext}"

    try:
        with open(saved_path, "wb") as f:
            content = await file.read()
            f.write(content)

        doc_title = title or (file.filename or "PDF文档").replace(file_ext, "")
        result = rag_service.ingest_pdf(
            collection_name=collection_name,
            file_path=str(saved_path),
            title=doc_title,
            api_key=api_key,
            embedding_model=embedding_model or None,
            embedding_provider=embedding_provider or None,
        )
        return CollectionResponse(success=True, message="PDF 文档入库成功", data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ImportError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF 入库失败: {e}")


@router.post("/documents/from-job", response_model=CollectionResponse)
def ingest_from_job(req: IngestFromJobRequest):
    """从已完成的 Pipeline 任务导入知识库。"""
    try:
        result = rag_service.ingest_from_pipeline_job(
            collection_name=req.collection_name,
            job_id=req.job_id,
            api_key=req.api_key,
            embedding_model=req.embedding_model or None,
            embedding_provider=req.embedding_provider or None,
        )
        return CollectionResponse(success=True, message="任务内容导入成功", data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"任务导入失败: {e}")


@router.get("/documents", response_model=CollectionResponse)
def list_documents(collection_name: str):
    """列出集合中的所有文档。"""
    try:
        documents = rag_service.list_documents(collection_name)
        return CollectionResponse(
            success=True,
            data={"documents": documents, "total": len(documents)},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取文档列表失败: {e}")


@router.delete("/documents/{doc_id}", response_model=CollectionResponse)
def delete_document(doc_id: int, collection_name: str):
    """删除文档及其向量数据。"""
    try:
        success = rag_service.delete_document(collection_name, doc_id)
        if not success:
            raise HTTPException(status_code=404, detail="文档不存在")
        return CollectionResponse(success=True, message="文档已删除")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除文档失败: {e}")


# ── 检索测试 ────────────────────────────────────────────────────────────────

@router.post("/search", response_model=CollectionResponse)
def test_search(req: SearchRequest):
    """测试 RAG 检索（调试用）。"""
    try:
        context = rag_service.retrieve_context(
            collection_name=req.collection_name,
            query_text=req.query,
            api_key=req.api_key,
            top_k=req.top_k,
            embedding_model=req.embedding_model or None,
            embedding_provider=req.embedding_provider or None,
        )
        return CollectionResponse(
            success=True,
            data={"context": context, "has_results": bool(context)},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"检索失败: {e}")
