"""
数据库连接配置（MySQL 专用）
────────────────────────────────────────────────────────────────────────────
职责：
  1. 根据 config.yaml / 环境变量 DATABASE_URL 创建同步 & 异步 SQLAlchemy Engine
  2. 提供 SessionLocal（同步 Session 工厂，供后台任务 / 脚本使用）
  3. 提供 AsyncSessionLocal（异步 Session 工厂，FastAPI async 路由专用）
  4. 提供 Base（所有 ORM 模型的声明式基类）
  5. 提供 get_db() / get_async_db()（FastAPI Depends 依赖注入）
  6. 提供 get_db_ctx() / get_async_db_ctx()（后台任务 / 脚本 / 测试用上下文管理器）
  7. 提供 check_db_connection()（服务启动时连通性自检）

驱动依赖：
  同步引擎  →  pymysql        （pip install pymysql）
  异步引擎  →  aiomysql       （pip install aiomysql）

URL 格式：
  同步：mysql+pymysql://user:pass@host:3306/dbname?charset=utf8mb4
  异步：mysql+aiomysql://user:pass@host:3306/dbname?charset=utf8mb4
  两者在本模块中自动互转，config.yaml 中只需填写同步格式。
────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


# ══════════════════════════════════════════════════════════════════════════════
# ORM 声明式基类（所有模型继承此类）
# ══════════════════════════════════════════════════════════════════════════════

class Base(DeclarativeBase):
    """
    SQLAlchemy 2.x 统一声明式基类。
    所有 ORM 模型继承此类，init_db.py 通过 Base.metadata.create_all() 建表。
    """
    pass


# ══════════════════════════════════════════════════════════════════════════════
# URL 转换工具
# ══════════════════════════════════════════════════════════════════════════════

def _to_async_url(url: str) -> str:
    """
    将 pymysql 同步 URL 转换为 aiomysql 异步 URL。
    若已是异步格式则原样返回。

    mysql+pymysql://...  →  mysql+aiomysql://...
    mysql://...          →  mysql+aiomysql://...
    """
    if url.startswith("mysql+pymysql://"):
        return url.replace("mysql+pymysql://", "mysql+aiomysql://", 1)
    if url.startswith("mysql://"):
        return url.replace("mysql://", "mysql+aiomysql://", 1)
    # 已是异步 URL，原样返回
    return url


def _to_sync_url(url: str) -> str:
    """
    将 aiomysql 异步 URL 转换为 pymysql 同步 URL。

    mysql+aiomysql://...  →  mysql+pymysql://...
    """
    if url.startswith("mysql+aiomysql://"):
        return url.replace("mysql+aiomysql://", "mysql+pymysql://", 1)
    return url


# ══════════════════════════════════════════════════════════════════════════════
# Engine 构建参数
# ══════════════════════════════════════════════════════════════════════════════

def _build_engine_kwargs(cfg) -> dict[str, Any]:
    """
    构造 MySQL Engine 的关键字参数。
    包含连接池配置和 pymysql/aiomysql 驱动参数。
    """
    kwargs: dict[str, Any] = {
        "echo":          cfg.db_echo,
        "pool_pre_ping": cfg.db_pool_pre_ping,   # 取连接前执行 SELECT 1 心跳检测
        "pool_recycle":  cfg.db_pool_recycle,     # 强制回收超时连接，防止 MySQL 断连
        "pool_size":     cfg.db_pool_size,        # 连接池常驻连接数
        "max_overflow":  cfg.db_max_overflow,     # 超出 pool_size 后允许的额外连接数
        "pool_timeout":  cfg.db_pool_timeout,     # 等待可用连接的超时（秒）
    }

    connect_args = cfg.db_connect_args or {}
    if connect_args:
        kwargs["connect_args"] = connect_args

    return kwargs


# ══════════════════════════════════════════════════════════════════════════════
# 同步引擎 & SessionLocal（后台任务 / 脚本 / 测试）
# ══════════════════════════════════════════════════════════════════════════════

def _build_sync_engine():
    cfg = get_settings()
    url = _to_sync_url(cfg.db_url)
    return create_engine(url, **_build_engine_kwargs(cfg))


engine = _build_sync_engine()

SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,   # commit 后对象属性仍可直接读取，不触发额外查询
)


# ══════════════════════════════════════════════════════════════════════════════
# 异步引擎 & AsyncSessionLocal（FastAPI async 路由）
# ══════════════════════════════════════════════════════════════════════════════

def _build_async_engine():
    cfg = get_settings()
    url = _to_async_url(cfg.db_url)
    return create_async_engine(url, **_build_engine_kwargs(cfg))


async_engine = _build_async_engine()

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=async_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI 依赖注入
# ══════════════════════════════════════════════════════════════════════════════

def get_db() -> Generator[Session, None, None]:
    """
    同步数据库依赖（普通路由）。
    出现异常时自动 rollback，正常结束时自动 commit。

    使用示例：
        @router.get("/jobs")
        def list_jobs(db: Session = Depends(get_db)):
            return db.query(PipelineJobModel).all()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """
    异步数据库依赖（async 路由）。
    出现异常时自动 rollback，正常结束时自动 commit。

    使用示例：
        @router.get("/jobs")
        async def list_jobs(db: AsyncSession = Depends(get_async_db)):
            result = await db.execute(select(PipelineJobModel))
            return result.scalars().all()
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ══════════════════════════════════════════════════════════════════════════════
# 上下文管理器（后台任务 / 脚本 / 测试，非 FastAPI 路由场景）
# ══════════════════════════════════════════════════════════════════════════════

@contextmanager
def get_db_ctx() -> Generator[Session, None, None]:
    """
    同步上下文管理器，适用于后台线程、init_db.py 脚本、单元测试。

    使用示例：
        with get_db_ctx() as db:
            db.add(PipelineJobModel(...))
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@asynccontextmanager
async def get_async_db_ctx() -> AsyncGenerator[AsyncSession, None]:
    """
    异步上下文管理器，适用于异步后台任务、异步测试。

    使用示例：
        async with get_async_db_ctx() as db:
            db.add(PipelineJobModel(...))
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ══════════════════════════════════════════════════════════════════════════════
# 健康检查
# ══════════════════════════════════════════════════════════════════════════════

def check_db_connection() -> bool:
    """
    同步测试 MySQL 连通性，服务启动或 init_db.py 运行时调用。
    返回 True 表示连接正常，False 表示失败（含错误信息打印）。
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        print(f"[DB] MySQL 连接失败: {exc}")
        return False


def ensure_database_schema() -> None:
    """
    创建当前 ORM 管理的表，并补齐历史版本缺失的轻量字段。

    SQLAlchemy 的 create_all() 不会修改已存在表结构；这里仅处理本项目
    从内存任务迁移到数据库任务时新增的兼容列。
    """
    # 确保模型已注册到 Base.metadata。
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine, checkfirst=True)

    inspector = inspect(engine)
    if "pipeline_jobs" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("pipeline_jobs")
    }
    alter_statements = []
    if "media_type" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE pipeline_jobs ADD COLUMN media_type VARCHAR(16) NULL"
        )
    if "image_paths" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE pipeline_jobs ADD COLUMN image_paths JSON NULL"
        )
    if "image_urls" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE pipeline_jobs ADD COLUMN image_urls JSON NULL"
        )
    if "article_body_markdown" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE pipeline_jobs ADD COLUMN article_body_markdown TEXT NULL"
            " COMMENT 'AI 生成的正文 Markdown（含图片占位符）'"
        )
    if "skip_image_generation" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE pipeline_jobs ADD COLUMN skip_image_generation BOOLEAN NOT NULL DEFAULT 0"
            " COMMENT '是否跳过封面图生成步骤'"
        )
    if "article_image_prompts" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE pipeline_jobs ADD COLUMN article_image_prompts JSON NULL"
            " COMMENT '图片提示词列表'"
        )
    if "cover_image_path" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE pipeline_jobs ADD COLUMN cover_image_path VARCHAR(512) NULL"
            " COMMENT '生成的封面图本地路径'"
        )
    if "knowledge_documents" in inspector.get_table_names():
        knowledge_columns = {
            column["name"] for column in inspector.get_columns("knowledge_documents")
        }
        if "vector_doc_id" not in knowledge_columns:
            alter_statements.append(
                "ALTER TABLE knowledge_documents ADD COLUMN vector_doc_id VARCHAR(64) NULL"
                " COMMENT 'ChromaDB 中用于标识该文档分块的 doc_id'"
            )

    if "content_tasks" in inspector.get_table_names():
        content_task_columns = {
            column["name"] for column in inspector.get_columns("content_tasks")
        }
        if "rag_top_k" not in content_task_columns:
            alter_statements.append(
                "ALTER TABLE content_tasks ADD COLUMN rag_top_k INT NOT NULL DEFAULT 5"
                " COMMENT 'RAG 检索返回的相关块数量'"
            )

        if "rag_embedding_model" not in content_task_columns:
            alter_statements.append(
                "ALTER TABLE content_tasks ADD COLUMN rag_embedding_model VARCHAR(128) NULL"
            )
        if "rag_embedding_provider" not in content_task_columns:
            alter_statements.append(
                "ALTER TABLE content_tasks ADD COLUMN rag_embedding_provider VARCHAR(32) NULL"
            )
        if "rag_embedding_api_key" not in content_task_columns:
            alter_statements.append(
                "ALTER TABLE content_tasks ADD COLUMN rag_embedding_api_key VARCHAR(256) NULL"
            )

    if not alter_statements:
        return

    with engine.begin() as conn:
        for statement in alter_statements:
            conn.execute(text(statement))
