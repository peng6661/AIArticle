"""
ChromaDB 向量存储封装
管理向量集合的创建、文档添加、检索和删除操作。
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ChromaDB 客户端单例
_client = None


def _sanitize_collection_name(name: str) -> str:
    """
    将集合名转换为 ChromaDB 兼容格式。
    ChromaDB 要求: 3-512 字符, 仅 [a-zA-Z0-9._-], 首尾必须是字母或数字。
    对中文等非 ASCII 字符使用短哈希替代。
    """
    # 如果已经是合法名称，直接返回
    if re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*[a-zA-Z0-9]$', name) and len(name) >= 3:
        return name
    # 用 md5 哈希生成合法名称，保留原名前缀方便调试
    safe_prefix = re.sub(r'[^a-zA-Z0-9]', '', name)[:10] or "kb"
    short_hash = hashlib.md5(name.encode()).hexdigest()[:12]
    return f"{safe_prefix}_{short_hash}"


def _get_client():
    """获取或创建 ChromaDB 客户端（持久化模式）。"""
    global _client
    if _client is None:
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
        except ImportError:
            raise ImportError("需要安装 chromadb：pip install chromadb")

        cfg = get_settings()
        persist_dir = cfg.rag_chroma_persist_dir
        Path(persist_dir).mkdir(parents=True, exist_ok=True)

        _client = chromadb.PersistentClient(path=persist_dir)
        logger.info(f"[ChromaDB] 初始化完成，持久化路径: {persist_dir}")
    return _client


def get_collection(name: str):
    """获取已存在的集合。"""
    client = _get_client()
    return client.get_collection(name=name)


def create_collection(name: str) -> str:
    """
    创建向量集合。

    Args:
        name: 集合名称（原始名称，可含中文）

    Returns:
        ChromaDB 中的实际集合名（安全格式）
    """
    cfg = get_settings()
    raw_name = f"{cfg.rag_collection_prefix}{name}"
    chroma_name = _sanitize_collection_name(raw_name)
    client = _get_client()
    collection = client.get_or_create_collection(
        name=chroma_name,
        metadata={"hnsw:space": "cosine"},
    )
    logger.info(f"[ChromaDB] 集合已创建/获取: {chroma_name} (原始: {name})")
    return chroma_name


def delete_collection(name: str) -> bool:
    """
    删除向量集合及其所有数据。

    Args:
        name: ChromaDB 中的实际集合名（安全格式）

    Returns:
        是否成功删除
    """
    try:
        client = _get_client()
        client.delete_collection(name=name)
        logger.info(f"[ChromaDB] 集合已删除: {name}")
        return True
    except Exception as e:
        logger.warning(f"[ChromaDB] 删除集合失败: {name}, 错误: {e}")
        return False


def add_documents(
    collection_name: str,
    doc_id: str,
    chunks: list[str],
    embeddings: list[list[float]],
) -> int:
    """
    将文档分块添加到向量集合。

    Args:
        collection_name: 集合全名
        doc_id: 文档 ID（用于后续按文档删除）
        chunks: 文本分块列表
        embeddings: 对应的向量列表

    Returns:
        添加的分块数量
    """
    if not chunks or not embeddings:
        return 0

    collection = get_collection(collection_name)

    # 生成唯一 ID：doc_id + chunk 序号
    ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
    metadatas = [{"doc_id": doc_id, "chunk_index": i} for i in range(len(chunks))]

    collection.add(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    logger.info(f"[ChromaDB] 添加 {len(chunks)} 个分块到集合 {collection_name}, doc_id={doc_id}")
    return len(chunks)


def search(
    collection_name: str,
    query_embedding: list[float],
    top_k: int = 5,
    doc_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    在向量集合中检索相似文档。

    Args:
        collection_name: 集合全名
        query_embedding: 查询向量
        top_k: 返回的最大结果数
        doc_id: 可选，限定在某个文档内检索

    Returns:
        检索结果列表，每项包含 text, distance, metadata
    """
    collection = get_collection(collection_name)

    where_filter = {"doc_id": doc_id} if doc_id else None

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where_filter,
        include=["documents", "distances", "metadatas"],
    )

    items = []
    if results and results["documents"] and results["documents"][0]:
        for i, doc in enumerate(results["documents"][0]):
            items.append({
                "text": doc,
                "distance": results["distances"][0][i] if results["distances"] else None,
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
            })

    return items


def delete_documents_by_source(collection_name: str, doc_id: str) -> int:
    """
    按文档 ID 删除该文档的所有分块。

    Args:
        collection_name: 集合全名
        doc_id: 文档 ID

    Returns:
        删除的分块数量
    """
    try:
        collection = get_collection(collection_name)
        # 先查询该 doc_id 的所有分块
        results = collection.get(
            where={"doc_id": doc_id},
            include=[],
        )
        if results and results["ids"]:
            collection.delete(ids=results["ids"])
            count = len(results["ids"])
            logger.info(f"[ChromaDB] 删除 {count} 个分块, doc_id={doc_id}")
            return count
        return 0
    except Exception as e:
        logger.warning(f"[ChromaDB] 删除分块失败: doc_id={doc_id}, 错误: {e}")
        return 0


def get_collection_stats(collection_name: str) -> dict[str, Any]:
    """获取集合统计信息。"""
    try:
        collection = get_collection(collection_name)
        count = collection.count()
        return {"name": collection_name, "count": count}
    except Exception:
        return {"name": collection_name, "count": 0}
