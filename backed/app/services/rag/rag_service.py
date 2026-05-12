"""
RAG 核心服务
编排文档入库、检索增强等完整流程。
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.db.database import get_db_ctx
from app.db.models import KnowledgeCollectionModel, KnowledgeDocumentModel
from app.services.rag import chunker, document_parser, embedding_service, vector_store
from app.services.rag.vector_store import _sanitize_collection_name

logger = logging.getLogger(__name__)


class RagService:
    """RAG 服务编排器。"""

    @staticmethod
    def _chroma_name(collection_name: str) -> str:
        """获取集合在 ChromaDB 中的安全名称。"""
        cfg = get_settings()
        return _sanitize_collection_name(f"{cfg.rag_collection_prefix}{collection_name}")

    def create_collection(self, name: str, description: str = "") -> dict:
        """创建知识库集合。"""
        cfg = get_settings()
        chroma_name = self._chroma_name(name)

        with get_db_ctx() as db:
            existing = db.scalar(
                select(KnowledgeCollectionModel).where(KnowledgeCollectionModel.name == name)
            )
            if existing:
                raise ValueError(f"集合 '{name}' 已存在")

            collection = KnowledgeCollectionModel(
                name=name,
                description=description,
                document_count=0,
                chunk_count=0,
            )
            db.add(collection)
            db.flush()
            collection_id = collection.id

        # 创建 ChromaDB 集合
        vector_store.create_collection(name)

        return {"id": collection_id, "name": name, "description": description}

    def list_collections(self) -> list[dict]:
        """列出所有知识库集合。"""
        with get_db_ctx() as db:
            collections = db.scalars(
                select(KnowledgeCollectionModel).order_by(KnowledgeCollectionModel.created_at.desc())
            ).all()
            return [
                {
                    "id": c.id,
                    "name": c.name,
                    "description": c.description,
                    "document_count": c.document_count,
                    "chunk_count": c.chunk_count,
                    "created_at": c.created_at.isoformat(),
                }
                for c in collections
            ]

    def delete_collection(self, collection_id: int) -> bool:
        """删除知识库集合及其所有数据。"""
        cfg = get_settings()
        with get_db_ctx() as db:
            collection = db.scalar(
                select(KnowledgeCollectionModel).where(KnowledgeCollectionModel.id == collection_id)
            )
            if not collection:
                return False

            chroma_name = self._chroma_name(collection.name)
            db.delete(collection)

        # 删除 ChromaDB 集合
        vector_store.delete_collection(chroma_name)
        return True

    def ingest_text(
        self,
        collection_name: str,
        content: str,
        title: str,
        source_type: str = "text",
        api_key: str = "",
        embedding_model: str | None = None,
        embedding_provider: str | None = None,
    ) -> dict:
        """
        文档入库：解析 → 分块 → embedding → 存储。

        Args:
            collection_name: 集合名称
            content: 文本内容
            title: 文档标题
            source_type: 来源类型 (text/markdown)
            api_key: API Key
            embedding_model: 向量模型名，留空使用 config 默认值

        Returns:
            文档信息
        """
        cfg = get_settings()

        # 1. 根据类型解析文本
        if source_type == "markdown":
            parsed_text = document_parser.parse_markdown(content)
        else:
            parsed_text = document_parser.parse_text(content)

        parsed_text = document_parser.clean_text(parsed_text)

        if not parsed_text:
            raise ValueError("文档内容为空")

        return self._ingest_parsed_text(
            collection_name=collection_name,
            text=parsed_text,
            title=title,
            source_type=source_type,
            api_key=api_key,
            embedding_model=embedding_model,
            embedding_provider=embedding_provider,
        )

    def ingest_pdf(
        self,
        collection_name: str,
        file_path: str,
        title: str,
        api_key: str = "",
        embedding_model: str | None = None,
        embedding_provider: str | None = None,
    ) -> dict:
        """PDF 文档入库。"""
        from pathlib import Path

        parsed_text = document_parser.parse_pdf(Path(file_path))
        parsed_text = document_parser.clean_text(parsed_text)

        if not parsed_text:
            raise ValueError("PDF 文档内容为空")

        return self._ingest_parsed_text(
            collection_name=collection_name,
            text=parsed_text,
            title=title,
            source_type="pdf",
            api_key=api_key,
            file_path=file_path,
            embedding_model=embedding_model,
            embedding_provider=embedding_provider,
        )

    def ingest_from_pipeline_job(
        self,
        collection_name: str,
        job_id: str,
        api_key: str = "",
        embedding_model: str | None = None,
        embedding_provider: str | None = None,
    ) -> dict:
        """从已完成的 pipeline 任务导入知识库。"""
        parsed_text = document_parser.parse_history_article(job_id)
        parsed_text = document_parser.clean_text(parsed_text)

        if not parsed_text:
            raise ValueError("任务内容为空")

        return self._ingest_parsed_text(
            collection_name=collection_name,
            text=parsed_text,
            title=f"Pipeline任务 {job_id[:8]}",
            source_type="history_article",
            api_key=api_key,
            source_job_id=job_id,
            embedding_model=embedding_model,
            embedding_provider=embedding_provider,
        )

    def _ingest_parsed_text(
        self,
        collection_name: str,
        text: str,
        title: str,
        source_type: str,
        api_key: str,
        file_path: str | None = None,
        source_job_id: str | None = None,
        embedding_model: str | None = None,
        embedding_provider: str | None = None,
    ) -> dict:
        """内部方法：将已解析的文本入库。"""
        cfg = get_settings()
        vector_doc_id = str(uuid.uuid4())[:8]

        # 1. 在数据库创建文档记录
        with get_db_ctx() as db:
            collection = db.scalar(
                select(KnowledgeCollectionModel).where(KnowledgeCollectionModel.name == collection_name)
            )
            if not collection:
                raise ValueError(f"集合 '{collection_name}' 不存在")

            doc = KnowledgeDocumentModel(
                collection_id=collection.id,
                title=title,
                source_type=source_type,
                file_path=file_path,
                vector_doc_id=vector_doc_id,
                chunk_count=0,
                status="processing",
                source_job_id=source_job_id,
            )
            db.add(doc)
            db.flush()
            doc_db_id = doc.id

        try:
            # 2. 分块
            chunks = chunker.chunk_text(
                text,
                chunk_size=cfg.rag_chunk_size,
                chunk_overlap=cfg.rag_chunk_overlap,
            )

            if not chunks:
                raise ValueError("分块结果为空")

            # 3. Embedding（优先使用 config 中专用的 embedding API Key）
            embed_key = cfg.rag_embedding_api_key or api_key
            embeddings = embedding_service.embed_texts(chunks, embed_key, model=embedding_model or None, provider=embedding_provider)

            # 4. 存入 ChromaDB
            chroma_name = self._chroma_name(collection_name)
            vector_store.add_documents(
                collection_name=chroma_name,
                doc_id=vector_doc_id,
                chunks=chunks,
                embeddings=embeddings,
            )

            # 5. 更新数据库记录
            with get_db_ctx() as db:
                db.execute(
                    update(KnowledgeDocumentModel)
                    .where(KnowledgeDocumentModel.id == doc_db_id)
                    .values(chunk_count=len(chunks), status="ready")
                )
                # 更新集合的文档数和分块数
                db.execute(
                    update(KnowledgeCollectionModel)
                    .where(KnowledgeCollectionModel.name == collection_name)
                    .values(
                        document_count=KnowledgeCollectionModel.document_count + 1,
                        chunk_count=KnowledgeCollectionModel.chunk_count + len(chunks),
                    )
                )

            return {
                "doc_id": doc_db_id,
                "vector_doc_id": vector_doc_id,
                "title": title,
                "chunk_count": len(chunks),
                "status": "ready",
            }

        except Exception as e:
            # 标记为失败
            with get_db_ctx() as db:
                db.execute(
                    update(KnowledgeDocumentModel)
                    .where(KnowledgeDocumentModel.id == doc_db_id)
                    .values(status="failed", error=str(e))
                )
            raise

    def retrieve_context(
        self,
        collection_name: str,
        query_text: str,
        api_key: str,
        top_k: int | None = None,
        embedding_model: str | None = None,
        embedding_provider: str | None = None,
        embedding_api_key: str | None = None,
    ) -> str:
        """
        检索相关上下文，返回拼接后的文本。

        Args:
            collection_name: 集合名称
            query_text: 查询文本（通常是转写文本的前 N 字）
            api_key: LLM API Key（若 config 配置了专用 embedding_api_key 则优先使用）
            top_k: 返回的最大结果数
            embedding_model: 向量模型名，留空使用 config 默认值
            embedding_api_key: 前端传入的向量模型专用 API Key

        Returns:
            拼接后的相关上下文文本
        """
        cfg = get_settings()
        if top_k is None:
            top_k = cfg.rag_top_k

        # 优先级：前端传入的 embedding_api_key > config 中专用的 embedding_api_key > 主 api_key
        embed_key = embedding_api_key or cfg.rag_embedding_api_key or api_key

        # 截取查询文本的前 1000 字做 embedding（避免过长）
        query_for_embedding = query_text[:1000]

        # 查询向量化
        query_embedding = embedding_service.embed_query(
            query_for_embedding, embed_key, model=embedding_model or None, provider=embedding_provider
        )

        # 在 ChromaDB 中检索
        chroma_name = self._chroma_name(collection_name)
        results = vector_store.search(
            collection_name=chroma_name,
            query_embedding=query_embedding,
            top_k=top_k,
        )

        if not results:
            return ""

        # 过滤低相似度结果（ChromaDB cosine distance: 0=完全相同, 2=完全不同）
        threshold = cfg.rag_similarity_threshold
        filtered = [r for r in results if r["distance"] is not None and r["distance"] < (2 - threshold)]

        if not filtered:
            return ""

        # 拼接上下文
        context_parts = [r["text"] for r in filtered]
        return "\n\n---\n\n".join(context_parts)

    def list_documents(self, collection_name: str) -> list[dict]:
        """列出集合中的所有文档。"""
        with get_db_ctx() as db:
            collection = db.scalar(
                select(KnowledgeCollectionModel).where(KnowledgeCollectionModel.name == collection_name)
            )
            if not collection:
                return []

            docs = db.scalars(
                select(KnowledgeDocumentModel)
                .where(KnowledgeDocumentModel.collection_id == collection.id)
                .order_by(KnowledgeDocumentModel.created_at.desc())
            ).all()

            return [
                {
                    "id": d.id,
                    "title": d.title,
                    "source_type": d.source_type,
                    "vector_doc_id": d.vector_doc_id,
                    "chunk_count": d.chunk_count,
                    "status": d.status,
                    "error": d.error,
                    "source_job_id": d.source_job_id,
                    "created_at": d.created_at.isoformat(),
                }
                for d in docs
            ]

    def delete_document(self, collection_name: str, doc_id: int) -> bool:
        """删除文档及其向量数据。"""
        vector_doc_id = ""
        chunk_count = 0
        chroma_name = self._chroma_name(collection_name)
        with get_db_ctx() as db:
            collection = db.scalar(
                select(KnowledgeCollectionModel).where(KnowledgeCollectionModel.name == collection_name)
            )
            if not collection:
                return False

            doc = db.scalar(
                select(KnowledgeDocumentModel).where(
                    KnowledgeDocumentModel.id == doc_id,
                    KnowledgeDocumentModel.collection_id == collection.id,
                )
            )
            if not doc:
                return False

            chunk_count = doc.chunk_count
            vector_doc_id = doc.vector_doc_id or ""
            db.delete(doc)

            # 更新集合统计
            db.execute(
                update(KnowledgeCollectionModel)
                .where(KnowledgeCollectionModel.id == collection.id)
                .values(
                    document_count=KnowledgeCollectionModel.document_count - 1,
                    chunk_count=KnowledgeCollectionModel.chunk_count - chunk_count,
                )
            )

        if vector_doc_id:
            deleted_chunks = vector_store.delete_documents_by_source(
                collection_name=chroma_name,
                doc_id=vector_doc_id,
            )
            logger.info(
                f"[RAG] 文档已删除: doc_id={doc_id}, vector_doc_id={vector_doc_id}, "
                f"vector_chunks={deleted_chunks}"
            )
        else:
            logger.warning(
                f"[RAG] 文档已从数据库删除，但缺少 vector_doc_id，无法精确清理向量分块: doc_id={doc_id}"
            )

        return True


# 全局单例
rag_service = RagService()
