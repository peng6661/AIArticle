"""
ORM 数据库模型
────────────────────────────────────────────────────────────────────────────
表结构：
  pipeline_jobs         主任务表（1 条记录 = 1 次完整流水线执行）
  pipeline_steps        步骤明细表（与 pipeline_jobs 一对多）

设计原则：
  · 大文本字段（HTML / 转写文本）用 Text 类型
  · JSON 结构（step data）用 JSON 类型（SQLite 以 TEXT 存储）
  · 枚举直接存字符串，无需 Enum 类型（便于跨数据库迁移）
  · 所有时间字段使用 DateTime(timezone=True)，UTC 存储
  · 外键关系在 Python 层用 relationship() 体现，级联删除
────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


# ── 工具：当前 UTC 时间 ────────────────────────────────────────────────────────
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════
# 主任务表
# ══════════════════════════════════════════════════════════════════════════════

class PipelineJobModel(Base):
    """
    流水线任务主表。
    每调用一次 POST /pipeline/step/download 或 POST /pipeline/run，
    就会在此表插入一行，记录任务全生命周期状态。

    对应内存对象：app.core.pipeline.PipelineJob
    """
    __tablename__ = "pipeline_jobs"

    # ── 主键 ──────────────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True,
        comment="自增主键（内部使用）",
    )
    job_id: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, index=True,
        comment="UUID 任务 ID，对外暴露",
    )

    # ── 任务状态 ──────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending",
        comment="任务状态：pending / running / success / failed",
    )
    current_step: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="当前正在执行的步骤名",
    )
    error: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="失败时的错误信息",
    )

    # ── Step 1：抖音视频下载 ──────────────────────────────────────────────────
    share_text: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="用户提交的抖音分享文本（含短链接）",
    )
    video_title: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="抖音视频标题",
    )
    video_path: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
        comment="下载后视频文件的绝对路径",
    )
    media_type: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
        comment="媒体类型：video / image",
    )
    image_paths: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="下载的图片本地路径列表（Instagram 多图等场景）",
    )
    image_urls: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="下载图片的原始 URL 列表",
    )

    # ── Step 2：音频提取 ──────────────────────────────────────────────────────
    audio_path: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
        comment="提取的音频文件绝对路径（mp3/wav）",
    )
    audio_format: Mapped[str | None] = mapped_column(
        String(8), nullable=True, default="mp3",
        comment="音频格式：mp3 / wav",
    )

    # ── Step 3：语音转写 ──────────────────────────────────────────────────────
    transcript_path: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
        comment="转写结果 .txt 文件路径",
    )
    transcript_text: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="完整转写文本内容",
    )
    transcribe_model: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default="small",
        comment="使用的 Whisper 模型大小",
    )
    language: Mapped[str | None] = mapped_column(
        String(8), nullable=True, default="zh",
        comment="转写语言代码",
    )

    # ── Step 4：AI 生成文章（JSON 结构化输出）────────────────────────────────
    article_title: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="AI 生成的文章标题",
    )
    article_body_markdown: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="AI 生成的正文 Markdown（含图片占位符）",
    )
    article_body_html: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="AI 生成的正文 HTML（含图片占位符，由 Markdown 转换而来）",
    )
    skip_image_generation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="是否跳过封面图生成步骤",
    )
    article_image_prompts: Mapped[list | None] = mapped_column(
        JSON, nullable=True, default=list,
        comment="图片提示词列表 [{\"id\": \"cover\", \"prompt\": \"...\"}]",
    )
    cover_image_path: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
        comment="生成的封面图本地路径",
    )
    text_model: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="生成文章使用的 AI 模型名",
    )
    topic: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="用户指定的文章主题",
    )

    # ── Step 6：微信 HTML 转换 ────────────────────────────────────────────────
    article_html: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="替换图片占位符后的最终微信格式 HTML",
    )
    wechat_html_path: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
        comment="最终 HTML 保存的本地文件路径",
    )

    # ── Step 7：微信草稿发布 ──────────────────────────────────────────────────
    wechat_appid: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="使用的公众号 AppID",
    )
    draft_media_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="微信草稿箱返回的 media_id",
    )
    draft_preview_url: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
        comment="微信草稿预览链接",
    )
    draft_author: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="草稿作者字段",
    )

    # ── 时间戳 ────────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now_utc,
        server_default=func.now(),
        comment="任务创建时间（UTC）",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now_utc,
        onupdate=_now_utc,
        server_default=func.now(),
        comment="最后更新时间（UTC）",
    )

    # ── 关系 ──────────────────────────────────────────────────────────────────
    steps: Mapped[list["PipelineStepModel"]] = relationship(
        "PipelineStepModel",
        back_populates="job",
        cascade="all, delete-orphan",   # 删除 job 时级联删除所有 steps
        order_by="PipelineStepModel.id",
        lazy="select",
    )

    # ── 索引 ──────────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_pipeline_jobs_status", "status"),
        Index("ix_pipeline_jobs_created_at", "created_at"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    def __repr__(self) -> str:
        return f"<PipelineJob job_id={self.job_id!r} status={self.status!r}>"


# ══════════════════════════════════════════════════════════════════════════════
# 步骤明细表
# ══════════════════════════════════════════════════════════════════════════════

class PipelineStepModel(Base):
    """
    流水线步骤执行记录表。
    一个 PipelineJob 包含 1-7 条 PipelineStep 记录（每步一条）。
    重试同一步骤时，新记录追加到此表（不覆盖旧记录）。

    对应内存对象：app.core.pipeline.StepResult
    """
    __tablename__ = "pipeline_steps"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True,
        comment="自增主键",
    )
    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pipeline_jobs.job_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的任务 UUID",
    )

    # ── 步骤信息 ──────────────────────────────────────────────────────────────
    step: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="步骤名称：download / extract_audio / transcribe / generate_article / "
                "generate_image / convert_html / publish_draft",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running",
        comment="步骤状态：running / success / failed",
    )
    message: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="步骤结束信息（成功摘要 或 错误详情）",
    )
    step_data: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="步骤输出的结构化数据（路径、title、prompt 等）",
    )

    # ── 时间 ──────────────────────────────────────────────────────────────────
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now_utc,
        comment="步骤开始时间（UTC）",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="步骤完成时间（UTC），未完成为 NULL",
    )

    # ── 执行耗时（冗余字段，方便性能分析）────────────────────────────────────
    duration_seconds: Mapped[float | None] = mapped_column(
        nullable=True,
        comment="步骤耗时（秒），finished_at - started_at",
    )

    # ── 关系 ──────────────────────────────────────────────────────────────────
    job: Mapped["PipelineJobModel"] = relationship(
        "PipelineJobModel",
        back_populates="steps",
    )

    # ── 索引 ──────────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_pipeline_steps_job_step", "job_id", "step"),
        Index("ix_pipeline_steps_status", "status"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    def __repr__(self) -> str:
        return (
            f"<PipelineStep job_id={self.job_id!r} "
            f"step={self.step!r} status={self.status!r}>"
        )


# ══════════════════════════════════════════════════════════════════════════════
# RAG 知识库集合表
# ══════════════════════════════════════════════════════════════════════════════

class KnowledgeCollectionModel(Base):
    """
    知识库集合表。
    一个集合对应一个主题知识库（如"AI技术"、"自媒体运营"），
    包含多个文档，文档经分块向量化后存储在 ChromaDB 中。
    """
    __tablename__ = "knowledge_collections"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True,
        comment="自增主键",
    )
    name: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False,
        comment="集合名称（唯一标识）",
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="集合描述",
    )
    document_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="集合中的文档数量",
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="集合中的总分块数量",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now_utc,
        server_default=func.now(),
        comment="创建时间（UTC）",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now_utc,
        onupdate=_now_utc,
        server_default=func.now(),
        comment="最后更新时间（UTC）",
    )

    documents: Mapped[list["KnowledgeDocumentModel"]] = relationship(
        "KnowledgeDocumentModel",
        back_populates="collection",
        cascade="all, delete-orphan",
        order_by="KnowledgeDocumentModel.id",
        lazy="select",
    )

    __table_args__ = (
        Index("ix_knowledge_collections_name", "name"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    def __repr__(self) -> str:
        return f"<KnowledgeCollection name={self.name!r} docs={self.document_count}>"


# ══════════════════════════════════════════════════════════════════════════════
# RAG 知识库文档表
# ══════════════════════════════════════════════════════════════════════════════

class KnowledgeDocumentModel(Base):
    """
    知识库文档表。
    每条记录代表一篇导入知识库的文档（文本、PDF、Markdown 或历史文章）。
    文档经解析、分块、向量化后存入 ChromaDB，本表记录元数据和状态。
    """
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True,
        comment="自增主键",
    )
    collection_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("knowledge_collections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的集合 ID",
    )
    title: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="文档标题",
    )
    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="来源类型：text / markdown / pdf / history_article",
    )
    file_path: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
        comment="原始文件路径（PDF 等上传文件）",
    )
    vector_doc_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="ChromaDB 中用于标识该文档分块的 doc_id",
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="文档分块数量",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="processing",
        comment="状态：processing / ready / failed",
    )
    error: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="处理失败时的错误信息",
    )
    source_job_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
        comment="来源 pipeline 任务 ID（history_article 类型时使用）",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now_utc,
        server_default=func.now(),
        comment="创建时间（UTC）",
    )

    collection: Mapped["KnowledgeCollectionModel"] = relationship(
        "KnowledgeCollectionModel",
        back_populates="documents",
    )

    __table_args__ = (
        Index("ix_knowledge_documents_collection", "collection_id"),
        Index("ix_knowledge_documents_status", "status"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    def __repr__(self) -> str:
        return f"<KnowledgeDocument title={self.title!r} status={self.status!r}>"


# ══════════════════════════════════════════════════════════════════════════════
# 智能写作任务表
# ══════════════════════════════════════════════════════════════════════════════

class ContentTaskModel(Base):
    """
    智能写作任务表（用于 Step 4 重构）。
    结合 LangGraph + RAG + MySQL 的深度文章生成系统。
    """
    __tablename__ = "content_tasks"

    # ── 主键 ──────────────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True,
        comment="自增主键",
    )
    task_id: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, index=True,
        comment="UUID 任务 ID",
    )

    # ── 关联 ──────────────────────────────────────────────────────────────────
    pipeline_job_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
        comment="关联的 pipeline 任务 ID（可选）",
    )

    # ── 任务状态 ──────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending",
        comment="任务状态：pending / processing / completed / failed",
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="重试次数",
    )
    error: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="失败时的错误信息",
    )

    # ── 输入 ──────────────────────────────────────────────────────────────────
    raw_transcript: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="原始转写文本（Step 3 输入）",
    )
    rag_collection: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="使用的 RAG 知识库集合名称",
    )
    rag_top_k: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5,
        comment="RAG 检索返回的相关块数量",
    )
    rag_embedding_model: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="用户选择的向量模型名，留空使用 config 默认值",
    )
    rag_embedding_provider: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="向量模型服务商 (siliconflow/zhipu)，留空使用 config 默认值",
    )
    rag_embedding_api_key: Mapped[str | None] = mapped_column(
        String(256), nullable=True,
        comment="向量模型专用 API Key，留空使用主 api_key",
    )

    # ── 中间产物 ──────────────────────────────────────────────────────────────
    article_outline: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="AI 生成的文章大纲（节点 A 输出）",
    )
    knowledge_context: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="RAG 检索到的知识背景（节点 A 输出）",
    )

    # ── 最终输出 ──────────────────────────────────────────────────────────────
    article_final: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="最终 Markdown 文章（节点 B 输出）",
    )
    article_title: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="文章标题",
    )
    image_prompt: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="封面图提示词（节点 B 输出）",
    )

    # ── 时间戳 ──────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now_utc,
        server_default=func.now(),
        comment="任务创建时间（UTC）",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now_utc,
        onupdate=_now_utc,
        server_default=func.now(),
        comment="最后更新时间（UTC）",
    )

    # ── 索引 ──────────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_content_tasks_status", "status"),
        Index("ix_content_tasks_created_at", "created_at"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    def __repr__(self) -> str:
        return f"<ContentTask task_id={self.task_id!r} status={self.status!r}>"
