"""
Embedding 缓存模块
避免对相同文本重复调用 embedding API。

缓存策略：
1. 内存缓存（LRU）：高速访问，服务重启后丢失
2. 文件缓存（可选）：持久化存储，重启后仍能命中

Key 设计：
  (query_text_hash, model, provider) -> embedding vector

使用方式：
  from app.services.rag.embedding_cache import embedding_cache
  
  # 查询缓存
  cached = embedding_cache.get(query_text, model, provider)
  
  # 写入缓存
  embedding_cache.set(query_text, model, provider, embedding_vector)
"""

from __future__ import annotations

import hashlib
import json
import logging
import pickle
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 内存缓存最大条目数（约占用 10000 * 1024维 * 4字节 ≈ 40MB）
MAX_MEMORY_CACHE_SIZE = 10000

# 缓存文件路径（项目根目录下的 .rag_cache）
CACHE_DIR = Path(__file__).resolve().parent.parent.parent.parent / ".rag_cache"
MEMORY_CACHE_FILE = CACHE_DIR / "embedding_cache.pkl"


class EmbeddingCache:
    """
    Embedding 向量缓存器（内存 + 文件双层）
    
    线程安全，支持 LRU 淘汰策略。
    """
    
    def __init__(self, max_size: int = MAX_MEMORY_CACHE_SIZE, enable_file_cache: bool = True):
        self.max_size = max_size
        self.enable_file_cache = enable_file_cache
        self._lock = threading.Lock()
        
        # 内存缓存：{key: {"vector": [...], "access_time": timestamp}}
        self._memory_cache: dict[str, dict] = {}
        self._access_counter = 0
        
        # 确保缓存目录存在
        if self.enable_file_cache:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self._load_from_file()
    
    def _make_key(self, query_text: str, model: Optional[str], provider: Optional[str]) -> str:
        """
        生成缓存 key。
        
        使用 query_text 的 SHA256 哈希 + model + provider，
        确保相同输入总是生成相同 key。
        """
        text_hash = hashlib.sha256(query_text.encode("utf-8")).hexdigest()
        model_str = model or "default"
        provider_str = provider or "default"
        return f"{text_hash}_{model_str}_{provider_str}"
    
    def get(self, query_text: str, model: Optional[str], provider: Optional[str]) -> Optional[list[float]]:
        """
        查询缓存。
        
        Returns:
            embedding vector（如果命中），否则 None
        """
        key = self._make_key(query_text, model, provider)
        
        with self._lock:
            if key in self._memory_cache:
                # 更新访问时间（LRU）
                self._memory_cache[key]["access_time"] = self._access_counter
                self._access_counter += 1
                vector = self._memory_cache[key]["vector"]
                logger.debug(f"[EmbeddingCache] 内存命中: {key[:20]}...")
                return vector
        
        # 内存未命中，尝试从文件加载
        if self.enable_file_cache:
            vector = self._load_key_from_file(key)
            if vector is not None:
                # 加载到内存缓存
                with self._lock:
                    self._memory_cache[key] = {
                        "vector": vector,
                        "access_time": self._access_counter,
                    }
                    self._access_counter += 1
                    # 淘汰过期条目
                    self._evict_if_needed()
                logger.debug(f"[EmbeddingCache] 文件命中: {key[:20]}...")
                return vector
        
        return None
    
    def set(self, query_text: str, model: Optional[str], provider: Optional[str], vector: list[float]):
        """写入缓存（内存 + 文件）。"""
        key = self._make_key(query_text, model, provider)
        
        with self._lock:
            self._memory_cache[key] = {
                "vector": vector,
                "access_time": self._access_counter,
            }
            self._access_counter += 1
            
            # 淘汰过期条目
            self._evict_if_needed()
        
        # 异步写入文件（避免阻塞）
        if self.enable_file_cache:
            self._save_key_to_file(key, vector)
        
        logger.debug(f"[EmbeddingCache] 已缓存: {key[:20]}...")
    
    def _evict_if_needed(self):
        """LRU 淘汰：当内存缓存超过 max_size 时，删除最久未访问的条目。"""
        if len(self._memory_cache) <= self.max_size:
            return
        
        # 按 access_time 排序，删除最老的 20% 条目
        sorted_keys = sorted(
            self._memory_cache.keys(),
            key=lambda k: self._memory_cache[k]["access_time"]
        )
        num_to_evict = max(1, len(sorted_keys) // 5)
        for old_key in sorted_keys[:num_to_evict]:
            del self._memory_cache[old_key]
            logger.debug(f"[EmbeddingCache] LRU淘汰: {old_key[:20]}...")
    
    def _load_from_file(self):
        """启动时从文件加载缓存到内存。"""
        if not MEMORY_CACHE_FILE.exists():
            return
        
        try:
            with open(MEMORY_CACHE_FILE, "rb") as f:
                file_cache = pickle.load(f)
            
            with self._lock:
                for key, vector in file_cache.items():
                    self._memory_cache[key] = {
                        "vector": vector,
                        "access_time": self._access_counter,
                    }
                    self._access_counter += 1
            
            logger.info(f"[EmbeddingCache] 从文件加载了 {len(file_cache)} 条缓存")
        except Exception as e:
            logger.warning(f"[EmbeddingCache] 加载文件缓存失败: {e}")
    
    def _save_key_to_file(self, key: str, vector: list[float]):
        """将单个 key 保存到文件（合并写入）。"""
        try:
            # 读取现有缓存
            file_cache = {}
            if MEMORY_CACHE_FILE.exists():
                with open(MEMORY_CACHE_FILE, "rb") as f:
                    file_cache = pickle.load(f)
            
            # 更新
            file_cache[key] = vector
            
            # 写回
            with open(MEMORY_CACHE_FILE, "wb") as f:
                pickle.dump(file_cache, f)
        except Exception as e:
            logger.warning(f"[EmbeddingCache] 写入文件缓存失败: {e}")
    
    def _load_key_from_file(self, key: str) -> Optional[list[float]]:
        """从文件读取单个 key。"""
        try:
            if not MEMORY_CACHE_FILE.exists():
                return None
            
            with open(MEMORY_CACHE_FILE, "rb") as f:
                file_cache = pickle.load(f)
            
            return file_cache.get(key)
        except Exception as e:
            logger.warning(f"[EmbeddingCache] 读取文件缓存失败: {e}")
            return None
    
    def clear(self):
        """清空所有缓存。"""
        with self._lock:
            self._memory_cache.clear()
            self._access_counter = 0
        
        if MEMORY_CACHE_FILE.exists():
            try:
                MEMORY_CACHE_FILE.unlink()
                logger.info("[EmbeddingCache] 已清空文件缓存")
            except Exception as e:
                logger.warning(f"[EmbeddingCache] 删除文件缓存失败: {e}")
        
        logger.info("[EmbeddingCache] 已清空所有缓存")
    
    def stats(self) -> dict:
        """返回缓存统计信息。"""
        with self._lock:
            return {
                "memory_entries": len(self._memory_cache),
                "max_size": self.max_size,
                "file_cache_exists": MEMORY_CACHE_FILE.exists(),
                "file_cache_size_mb": (
                    MEMORY_CACHE_FILE.stat().st_size / 1024 / 1024
                    if MEMORY_CACHE_FILE.exists()
                    else 0
                ),
            }


# 全局缓存实例
embedding_cache = EmbeddingCache(enable_file_cache=True)
