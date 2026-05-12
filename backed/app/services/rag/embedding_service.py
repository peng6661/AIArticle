"""
Embedding 服务
调用智谱 AI 的 embedding-3 模型 API 将文本转换为向量。
复用项目已有的 OpenAI SDK。
"""
from __future__ import annotations

import importlib
import logging
from typing import Any

from app.core.config import get_settings
from app.services.rag.embedding_cache import embedding_cache

logger = logging.getLogger(__name__)

# 智谱 embedding API 端点
ZHIPU_EMBEDDING_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"

# 单次 API 调用的最大文本数（智谱 API 限制）
MAX_BATCH_SIZE = 16


def _ensure_openai():
    try:
        return importlib.import_module("openai")
    except ImportError:
        raise ImportError("未检测到依赖 openai；请先执行 pip install -r requirements.txt")


def embed_texts(
    texts: list[str],
    api_key: str,
    model: str | None = None,
    base_url: str | None = None,
    provider: str | None = None,
) -> list[list[float]]:
    """
    批量文本转向量。

    Args:
        texts: 待向量化的文本列表
        api_key: API Key
        model: embedding 模型名，默认从 config 读取
        base_url: API 端点，传入时优先使用
        provider: 服务商名 (siliconflow/zhipu)，base_url 为空时据此解析端点

    Returns:
        向量列表，与输入 texts 一一对应
    """
    if not texts:
        return []

    cfg = get_settings()
    if base_url is None:
        base_url = cfg.get_embedding_base_url(provider)
    if model is None:
        model = cfg.get_embedding_default_model(provider)

    # 打印 Embedding 配置，方便排查 429 / 鉴权等问题
    masked_key = (api_key[:6] + "****" + api_key[-4:]) if api_key and len(api_key) > 10 else "（空）"
    print(f"\n{'='*60}")
    print(f"[Embedding] 配置信息")
    print(f"  model    = {model}")
    print(f"  base_url = {base_url}")
    print(f"  api_key  = {masked_key}")
    print(f"  texts    = {len(texts)} 条")
    print(f"{'='*60}\n")

    openai_mod = _ensure_openai()
    client = openai_mod.OpenAI(api_key=api_key, base_url=base_url)

    all_embeddings: list[list[float]] = []

    # 分批调用，避免单次请求过大
    for i in range(0, len(texts), MAX_BATCH_SIZE):
        batch = texts[i:i + MAX_BATCH_SIZE]
        response = client.embeddings.create(
            model=model,
            input=batch,
        )
        # 按 index 排序确保顺序正确
        sorted_data = sorted(response.data, key=lambda x: x.index)
        for item in sorted_data:
            all_embeddings.append(item.embedding)

    return all_embeddings


def embed_query(
    query: str,
    api_key: str,
    model: str | None = None,
    base_url: str | None = None,
    provider: str | None = None,
) -> list[float]:
    """
    单条查询文本转向量（带缓存）。

    Args:
        query: 查询文本
        api_key: API Key
        model: embedding 模型名
        base_url: API 端点
        provider: 服务商名 (siliconflow/zhipu)

    Returns:
        向量
    """
    # 1. 先查缓存
    cached = embedding_cache.get(query, model, provider)
    if cached is not None:
        print(f"[EmbeddingCache] 命中缓存，跳过 API 调用 ({len(query)} 字符)")
        return cached
    
    # 2. 缓存未命中，调用 API
    print(f"[EmbeddingCache] 缓存未命中，调用 API ({len(query)} 字符)")
    results = embed_texts([query], api_key, model, base_url, provider)
    vector = results[0]
    
    # 3. 写入缓存
    embedding_cache.set(query, model, provider, vector)
    
    return vector
