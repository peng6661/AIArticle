"""
ORM 数据库模型
────────────────────────────────────────────────────────────────────────────
表结构：
  pipeline_jobs         主任务表（1 条记录 = 1 次完整流水线执行）
  pipeline_steps        步骤明细表（与 pipeline_jobs 一对多）
  wechat_image_assets   正文图片素材表（与 pipeline_jobs 一对多）

设计原则：
  · 大文本字段（HTML / 转写文本）用 Text 类型
  · JSON 结构（image_prompts / step data）用 JSON 类型（SQLite 以 TEXT 存储）
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
    article_body_html: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="AI 生成的正文 HTML（含图片占位符）",
    )
    article_image_prompts: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment='图片 prompt 列表，格式：[{"id":"cover","prompt":"..."},...]',
    )
    generate_inline_images: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        comment="是否生成文中插图（False=仅封面）",
    )
    text_model: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="生成文章使用的 AI 模型名",
    )
    topic: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="用户指定的文章主题",
    )

    # ── Step 5：图片生成 & 微信素材上传 ──────────────────────────────────────
    image_path: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
        comment="封面图本地绝对路径（第一张生成图）",
    )
    image_model: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="生成图片使用的 AI 模型名",
    )
    image_size: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
        comment="生成图片尺寸，如 1664x928",
    )
    # 正文图片详情存在 wechat_image_assets 子表，这里只存聚合 JSON 作为缓存
    wechat_image_map: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment='正文图片映射缓存 {"img_01":{"local_path":"...","wechat_url":"...",...}}',
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
    image_assets: Mapped[list["WechatImageAssetModel"]] = relationship(
        "WechatImageAssetModel",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="WechatImageAssetModel.id",
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
# 微信图片素材表
# ══════════════════════════════════════════════════════════════════════════════

class WechatImageAssetModel(Base):
    """
    正文图片素材记录表。
    将 PipelineJob.wechat_image_map（JSON）拆成独立行，便于查询和复用。
    每张图片占一行，包含本地路径、微信素材 URL、media_id。

    注意：封面图（id=cover）也记录在此表，is_cover=True。
    """
    __tablename__ = "wechat_image_assets"

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

    # ── 图片标识 ──────────────────────────────────────────────────────────────
    img_id: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="图片占位符 ID：cover / img_01 / img_02 ...",
    )
    is_cover: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="是否为封面图（True=封面，作为草稿 thumb_media_id）",
    )

    # ── AI 生图 Prompt ────────────────────────────────────────────────────────
    prompt: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="生成此图使用的 AI prompt",
    )
    image_model: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="生成此图使用的模型名",
    )
    image_size: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
        comment="生成尺寸，如 1664x928",
    )

    # ── 本地存储 ──────────────────────────────────────────────────────────────
    local_path: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
        comment="图片下载后的本地绝对路径",
    )

    # ── 微信素材库 ────────────────────────────────────────────────────────────
    wechat_url: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
        comment="上传微信素材库后返回的图片 URL（用于正文 <img src>）",
    )
    wechat_media_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="上传微信素材库后返回的 media_id（封面图用此值）",
    )
    uploaded_to_wechat: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="是否已成功上传到微信素材库",
    )

    # ── 时间戳 ────────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now_utc,
        server_default=func.now(),
        comment="记录创建时间（UTC）",
    )

    # ── 关系 ──────────────────────────────────────────────────────────────────
    job: Mapped["PipelineJobModel"] = relationship(
        "PipelineJobModel",
        back_populates="image_assets",
    )

    # ── 索引 ──────────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_wechat_image_assets_job_img", "job_id", "img_id"),
        Index("ix_wechat_image_assets_cover", "job_id", "is_cover"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    def __repr__(self) -> str:
        return (
            f"<WechatImageAsset job_id={self.job_id!r} "
            f"img_id={self.img_id!r} cover={self.is_cover}>"
        )
