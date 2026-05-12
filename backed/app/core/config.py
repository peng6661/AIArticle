"""
核心配置加载模块
支持 config.yaml + 环境变量覆盖
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class Settings:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    def get(self, *keys: str, default: Any = None) -> Any:
        node = self._data
        for key in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(key, default)
            if node is None:
                return default
        return node

    # ── 路径 ──────────────────────────────────────────
    @property
    def downloads_dir(self) -> Path:
        return Path(self.get("paths", "downloads_dir", default="downloads"))

    @property
    def outputs_dir(self) -> Path:
        return Path(self.get("paths", "outputs_dir", default="outputs"))

    @property
    def transcripts_dir(self) -> Path:
        return Path(self.get("paths", "transcripts_dir", default="transcripts"))

    # ── 抖音 ─────────────────────────────────────────
    @property
    def douyin_user_agent(self) -> str:
        return self.get("douyin", "user_agent", default="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1")

    @property
    def douyin_referer(self) -> str:
        return self.get("douyin", "referer", default="https://www.douyin.com/")

    @property
    def douyin_timeout_short(self) -> int:
        return self.get("douyin", "timeout_short", default=5)

    @property
    def douyin_timeout_medium(self) -> int:
        return self.get("douyin", "timeout_medium", default=10)

    @property
    def douyin_timeout_download(self) -> int:
        return self.get("douyin", "timeout_download", default=30)

    # ── 音频 ─────────────────────────────────────────
    @property
    def audio_default_format(self) -> str:
        return self.get("audio", "default_format", default="mp3")

    @property
    def audio_ffmpeg_mp3_quality(self) -> str:
        return self.get("audio", "ffmpeg_mp3_quality", default="2")

    # ── 转写 ─────────────────────────────────────────
    @property
    def transcribe_default_model(self) -> str:
        return self.get("transcribe", "default_model", default="small")

    @property
    def transcribe_default_language(self) -> str:
        return self.get("transcribe", "default_language", default="zh")

    @property
    def transcribe_device(self) -> str:
        """转写设备：auto / cpu / cuda。auto 模式自动检测 CUDA 可用性。"""
        return os.getenv("TRANSCRIBE_DEVICE") or self.get("transcribe", "device", default="auto")

    @property
    def transcribe_compute_type(self) -> str:
        """转写计算精度：auto / int8 / float16 等。auto 模式根据设备自动选择。"""
        return os.getenv("TRANSCRIBE_COMPUTE_TYPE") or self.get("transcribe", "compute_type", default="auto")

    @property
    def transcribe_vad_filter(self) -> bool:
        return self.get("transcribe", "vad_filter", default=True)

    # ── SiliconFlow ───────────────────────────────────
    @property
    def siliconflow_base_url(self) -> str:
        return self.get("siliconflow", "base_url", default="https://api.siliconflow.cn/v1")

    @property
    def siliconflow_default_text_model(self) -> str:
        return self.get("siliconflow", "default_text_model", default="Qwen/Qwen3-14B")

    @property
    def siliconflow_default_temperature(self) -> float:
        return float(self.get("siliconflow", "default_temperature", default=0.7))

    @property
    def siliconflow_max_tokens(self) -> int:
        return int(self.get("siliconflow", "max_tokens", default=4096))

    @property
    def siliconflow_default_image_model(self) -> str:
        return self.get("siliconflow", "default_image_model", default="stabilityai/stable-diffusion-3-5-large")

    @property
    def siliconflow_default_image_size(self) -> str:
        return self.get("siliconflow", "default_image_size", default="1024x768")

    @property
    def siliconflow_target_image_size(self) -> str | None:
        val = self.get("siliconflow", "target_image_size", default="")
        return val if val else None

    # ── 智谱 AI ───────────────────────────────────────
    @property
    def zhipu_base_url(self) -> str:
        return self.get("zhipu", "base_url", default="https://open.bigmodel.cn/api/paas/v4")

    @property
    def zhipu_default_text_model(self) -> str:
        return self.get("zhipu", "default_text_model", default="glm-4-flash")

    @property
    def zhipu_default_temperature(self) -> float:
        return float(self.get("zhipu", "default_temperature", default=0.7))

    @property
    def zhipu_max_tokens(self) -> int:
        return int(self.get("zhipu", "max_tokens", default=4096))

    @property
    def zhipu_default_image_model(self) -> str:
        return self.get("zhipu", "default_image_model", default="cogview-3")

    @property
    def zhipu_default_image_size(self) -> str:
        return self.get("zhipu", "default_image_size", default="1024x1024")

    @property
    def zhipu_target_image_size(self) -> str | None:
        val = self.get("zhipu", "target_image_size", default="")
        return val if val else None

    # ── Embedding Provider 路由 ──────────────────────────
    EMBEDDING_PROVIDER_URLS: dict[str, str] = {
        "siliconflow": "https://api.siliconflow.cn/v1",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    }
    EMBEDDING_PROVIDER_DEFAULT_MODELS: dict[str, str] = {
        "siliconflow": "Qwen/Qwen3-Embedding-8B",
        "zhipu": "embedding-3",
    }


    def get_embedding_base_url(self, provider: str | None = None) -> str:
        """根据服务商名返回 embedding API 端点。provider 为空时使用 config 默认值。"""
        if provider and provider in self.EMBEDDING_PROVIDER_URLS:
            return self.EMBEDDING_PROVIDER_URLS[provider]
        return self.rag_embedding_base_url

    def get_embedding_default_model(self, provider: str | None = None) -> str:
        """根据服务商名返回默认 embedding 模型。provider 为空时使用 config 默认值。"""
        if provider and provider in self.EMBEDDING_PROVIDER_DEFAULT_MODELS:
            return self.EMBEDDING_PROVIDER_DEFAULT_MODELS[provider]
        return self.rag_embedding_model

    # ── AI Provider 路由 ──────────────────────────────
    def get_ai_provider_config(self, provider: str) -> dict:
        """
        根据 ai_provider 返回对应的 base_url、模型、参数。
        provider: \"siliconflow\" | \"zhipu\"
        """
        if provider == "zhipu":
            return {
                "base_url": self.zhipu_base_url,
                "default_text_model": self.zhipu_default_text_model,
                "default_temperature": self.zhipu_default_temperature,
                "max_tokens": self.zhipu_max_tokens,
            }
        return {
            "base_url": self.siliconflow_base_url,
            "default_text_model": self.siliconflow_default_text_model,
            "default_temperature": self.siliconflow_default_temperature,
            "max_tokens": self.siliconflow_max_tokens,
        }

    # ── RAG 知识库 ─────────────────────────────────────
    @property
    def rag_enabled(self) -> bool:
        return bool(self.get("rag", "enabled", default=True))

    @property
    def rag_chroma_persist_dir(self) -> str:
        return self.get("rag", "chroma_persist_dir", default="data/chroma_db")

    @property
    def rag_collection_prefix(self) -> str:
        return self.get("rag", "collection_prefix", default="kb_")

    @property
    def rag_embedding_model(self) -> str:
        return self.get("rag", "embedding_model", default="embedding-3")

    @property
    def rag_embedding_base_url(self) -> str:
        """向量模型 API 端点，可独立于 LLM 服务商配置。"""
        return self.get("rag", "embedding_base_url", default="https://open.bigmodel.cn/api/paas/v4")

    @property
    def rag_embedding_api_key(self) -> str:
        """向量模型专用 API Key。留空则使用前端传入的 api_key。"""
        return os.getenv("RAG_EMBEDDING_API_KEY") or self.get("rag", "embedding_api_key", default="")

    @property
    def rag_chunk_size(self) -> int:
        return int(self.get("rag", "chunk_size", default=500))

    @property
    def rag_chunk_overlap(self) -> int:
        return int(self.get("rag", "chunk_overlap", default=100))

    @property
    def rag_top_k(self) -> int:
        return int(self.get("rag", "top_k", default=5))

    @property
    def rag_similarity_threshold(self) -> float:
        return float(self.get("rag", "similarity_threshold", default=0.3))

    # ── YouTube ──────────────────────────────────────
    @property
    def youtube_cookies_source(self) -> str:
        """cookies 来源：browser = 从本地浏览器读取，file = 从文件读取，none = 不使用"""
        return self.get("youtube", "cookies_source", default="file")

    @property
    def youtube_browser(self) -> str:
        """浏览器类型（chrome/firefox/edge/opera/vivaldi/brave/chromium）"""
        return self.get("youtube", "browser", default="chrome")

    @property
    def youtube_cookies_file(self) -> str:
        """cookies 文件路径（Netscape 格式，相对于 backed/ 目录）"""
        return self.get("youtube", "cookies_file", default="cookies_youtube.txt")

    @property
    def youtube_js_runtime(self) -> str:
        """
        yt-dlp JS 运行时路径，用于生成 PO Token（新版 yt-dlp 必须）。
        支持：node/nodejs/deno/bun/quickjs
        设置为 auto 时自动在 PATH 中查找 node/deno/bun
        留空则不配置（部分视频会缺失格式）
        """
        return self.get("youtube", "js_runtime", default="auto")

    @property
    def youtube_remote_components(self) -> str:
        """
        yt-dlp 远程组件配置，用于 JS 挑战求解和 PO Token 生成。
        参考：https://github.com/yt-dlp/yt-dlp/wiki/EJS
        可选值：
          "github"  — 从 GitHub 下载挑战脚本（推荐）
          "npm"     — 从 npm 下载
          "github,npm" — 多个源
          "none"    — 不启用（旧版 yt-dlp 可用）
        留空默认 "github"
        """
        return self.get("youtube", "remote_components", default="github")



    # ── 文章 ─────────────────────────────────────────
    @property
    def article_default_topic(self) -> str:
        return self.get("article", "default_topic", default="AI学习工具与效率革命")

    @property
    def article_default_extra_requirements(self) -> str:
        return self.get("article", "default_extra_requirements", default="")

    # ── 微信 ─────────────────────────────────────────
    @property
    def wechat_appid(self) -> str:
        return os.getenv("WECHAT_APPID") or self.get("wechat", "appid", default="")

    @property
    def wechat_appsecret(self) -> str:
        return os.getenv("WECHAT_APPSECRET") or self.get("wechat", "appsecret", default="")

    @property
    def wechat_default_author(self) -> str:
        return self.get("wechat", "default_author", default="AIcreator")

    @property
    def wechat_default_digest(self) -> str:
        return self.get("wechat", "default_digest", default="")

    @property
    def wechat_default_content_source_url(self) -> str:
        return self.get("wechat", "default_content_source_url", default="")

    @property
    def wechat_need_open_comment(self) -> int:
        return int(self.get("wechat", "need_open_comment", default=0))

    @property
    def wechat_only_fans_can_comment(self) -> int:
        return int(self.get("wechat", "only_fans_can_comment", default=0))

    @property
    def wechat_default_original_notice(self) -> str:
        return self.get("wechat", "default_original_notice", default="")

    @property
    def wechat_api_base(self) -> str:
        return self.get("wechat", "api_base", default="https://api.weixin.qq.com")

    # ── 数据库（MySQL 专用）────────────────────────────
    @property
    def db_url(self) -> str:
        """
        数据库连接 URL。
        优先级：环境变量 DATABASE_URL > config.yaml database.url
        URL 格式：mysql+pymysql://user:pass@host:3306/dbname?charset=utf8mb4
        """
        return (
            os.getenv("DATABASE_URL")
            or self.get(
                "database", "url",
                default="mysql+pymysql://root:your_password@127.0.0.1:3306/aicreator?charset=utf8mb4",
            )
        )

    @property
    def db_echo(self) -> bool:
        return bool(self.get("database", "echo", default=False))

    @property
    def db_pool_pre_ping(self) -> bool:
        return bool(self.get("database", "pool_pre_ping", default=True))

    @property
    def db_pool_recycle(self) -> int:
        """MySQL 默认 8 小时断连，建议设置为 3600（1 小时）"""
        return int(self.get("database", "pool_recycle", default=3600))

    @property
    def db_pool_size(self) -> int:
        return int(self.get("database", "pool_size", default=10))

    @property
    def db_max_overflow(self) -> int:
        return int(self.get("database", "max_overflow", default=20))

    @property
    def db_pool_timeout(self) -> int:
        return int(self.get("database", "pool_timeout", default=30))

    @property
    def db_connect_args(self) -> dict:
        """pymysql 驱动级连接参数（connect_timeout / read_timeout / write_timeout）"""
        args = self.get("database", "connect_args", default={})
        return args if isinstance(args, dict) else {}

    # ── MySQL 建库专用配置（init_db.py --create-db 使用）──
    @property
    def mysql_host(self) -> str:
        return self.get("database", "mysql", "host", default="127.0.0.1")

    @property
    def mysql_port(self) -> int:
        return int(self.get("database", "mysql", "port", default=3306))

    @property
    def mysql_user(self) -> str:
        return self.get("database", "mysql", "user", default="root")

    @property
    def mysql_password(self) -> str:
        """支持环境变量 MYSQL_PASSWORD 覆盖，避免明文密码提交到版本控制"""
        return (
            os.getenv("MYSQL_PASSWORD")
            or self.get("database", "mysql", "password", default="")
        )

    @property
    def mysql_database(self) -> str:
        return self.get("database", "mysql", "database", default="aicreator")

    @property
    def mysql_charset(self) -> str:
        return self.get("database", "mysql", "charset", default="utf8mb4")

    @property
    def mysql_collation(self) -> str:
        return self.get("database", "mysql", "collation", default="utf8mb4_unicode_ci")

    # ── 服务器 ────────────────────────────────────────
    @property
    def server_host(self) -> str:
        return self.get("server", "host", default="0.0.0.0")

    @property
    def server_port(self) -> int:
        return int(self.get("server", "port", default=8000))

    @property
    def server_title(self) -> str:
        return self.get("server", "title", default="AIcreator API")

    @property
    def server_description(self) -> str:
        return self.get("server", "description", default="")

    @property
    def server_version(self) -> str:
        return self.get("server", "version", default="1.0.0")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"配置文件不存在: {CONFIG_PATH}")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Settings(data)
