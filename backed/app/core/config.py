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
    def siliconflow_default_image_model(self) -> str:
        return self.get("siliconflow", "default_image_model", default="black-forest-labs/FLUX.1-schnell")

    @property
    def siliconflow_default_temperature(self) -> float:
        return float(self.get("siliconflow", "default_temperature", default=0.7))

    @property
    def siliconflow_default_image_size(self) -> str:
        return self.get("siliconflow", "default_image_size", default="1664x928")

    @property
    def siliconflow_max_tokens(self) -> int:
        return int(self.get("siliconflow", "max_tokens", default=4096))

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
