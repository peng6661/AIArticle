"""
流水线状态管理
使用 MySQL 持久化存储每个 job 的状态，服务重启后任务历史仍可查询
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from app.db.database import get_db_ctx
from app.db.models import PipelineJobModel, PipelineStepModel

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    SUCCESS = "success"
    FAILED = "failed"


class StepName(str, Enum):
    DOWNLOAD = "download"                    # 步骤1: 抖音下载视频
    EXTRACT_AUDIO = "extract_audio"          # 步骤2: 提取音频
    TRANSCRIBE = "transcribe"                # 步骤3: 语音转文字
    GENERATE_ARTICLE = "generate_article"   # 步骤4: 生成文章（JSON 结构化输出）
    GENERATE_IMAGE = "generate_image"        # 步骤5: 并发生成配图 + 上传微信素材
    CONVERT_HTML = "convert_html"            # 步骤6: 替换占位符，转换微信 HTML
    PUBLISH_DRAFT = "publish_draft"          # 步骤7: 发布草稿到微信


@dataclass
class StepResult:
    step: StepName
    status: JobStatus
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: str | None = None


@dataclass
class PipelineJob:
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: JobStatus = JobStatus.PENDING
    current_step: StepName | None = None
    steps: list[StepResult] = field(default_factory=list)

    # ── Step 1-3 产物 ─────────────────────────────────────────────────────────
    share_text: str | None = None
    video_path: str | None = None
    audio_path: str | None = None
    transcript_path: str | None = None
    transcript_text: str | None = None
    # Instagram 多图帖子支持
    media_type: str | None = None           # video / image
    image_paths: list[str] = field(default_factory=list)  # 所有下载的图片路径
    image_urls: list[str] = field(default_factory=list)  # 所有图片的原始 URL

    # ── Step 4 产物：AI JSON 结构化输出 ───────────────────────────────────────
    article_title: str | None = None            # {"title": "..."}
    article_body_markdown: str | None = None    # {"content": "## 标题\n\n段落【图片占位符:img_01】"}
    article_body_html: str | None = None        # {"content": "<p>...【图片占位符:img_01】...</p>"}
    article_image_prompts: list | None = None   # [{"id":"img_01","prompt":"..."}]
    generate_inline_images: bool = True         # Step4 写入，False 时仅封面
    skip_publish: bool = False                  # 一键流程是否跳过 Step7 发布草稿

    # ── Step 5 产物：图片生成 & 微信素材上传 ─────────────────────────────────
    image_path: str | None = None               # 封面图（第一张）绝对路径
    # {"img_01": {"local_path": "...", "wechat_url": "...", "media_id": "..."}}
    wechat_image_map: dict | None = None

    # ── Step 6 产物：最终微信 HTML ────────────────────────────────────────────
    article_html: str | None = None             # 替换占位符后的最终正文 HTML
    wechat_html_path: str | None = None         # 保存到本地文件的路径

    # ── Step 7 产物 ────────────────────────────────────────────────────────────
    draft_media_id: str | None = None
    draft_preview_url: str | None = None

    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class PipelineStore:
    """PipelineJob 的持久化仓储，向路由层暴露 dataclass 接口。"""

    @staticmethod
    def _step_to_model(job_id: str, step: StepResult) -> PipelineStepModel:
        started_at = datetime.fromisoformat(step.started_at)
        finished_at = (
            datetime.fromisoformat(step.finished_at)
            if step.finished_at else None
        )
        duration = None
        if finished_at:
            duration = (finished_at - started_at).total_seconds()

        return PipelineStepModel(
            job_id=job_id,
            step=str(step.step.value if isinstance(step.step, StepName) else step.step),
            status=str(step.status.value if isinstance(step.status, JobStatus) else step.status),
            message=step.message,
            step_data=step.data,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration,
        )

    @staticmethod
    def _model_to_step(model: PipelineStepModel) -> StepResult:
        return StepResult(
            step=StepName(model.step),
            status=JobStatus(model.status),
            message=model.message or "",
            data=model.step_data or {},
            started_at=model.started_at.isoformat(),
            finished_at=model.finished_at.isoformat() if model.finished_at else None,
        )

    @staticmethod
    def _model_to_job(model: PipelineJobModel) -> PipelineJob:
        job = PipelineJob(
            job_id=model.job_id,
            status=JobStatus(model.status),
            current_step=StepName(model.current_step) if model.current_step else None,
            steps=[PipelineStore._model_to_step(step) for step in model.steps],
            share_text=model.share_text,
            video_path=model.video_path,
            audio_path=model.audio_path,
            transcript_path=model.transcript_path,
            transcript_text=model.transcript_text,
            media_type=model.media_type,
            image_paths=model.image_paths or [],
            image_urls=model.image_urls or [],
            article_title=model.article_title,
            article_body_markdown=model.article_body_markdown,
            article_body_html=model.article_body_html,
            article_image_prompts=model.article_image_prompts,
            generate_inline_images=model.generate_inline_images,
            skip_publish=model.skip_publish,
            image_path=model.image_path,
            wechat_image_map=model.wechat_image_map,
            article_html=model.article_html,
            wechat_html_path=model.wechat_html_path,
            draft_media_id=model.draft_media_id,
            draft_preview_url=model.draft_preview_url,
            error=model.error,
            created_at=model.created_at.isoformat(),
            updated_at=model.updated_at.isoformat(),
        )
        return job

    @staticmethod
    def _apply_job_to_model(job: PipelineJob, model: PipelineJobModel) -> None:
        model.status = str(job.status.value if isinstance(job.status, JobStatus) else job.status)
        model.current_step = (
            str(job.current_step.value if isinstance(job.current_step, StepName) else job.current_step)
            if job.current_step else None
        )
        model.error = job.error

        model.share_text = job.share_text
        model.video_path = job.video_path
        model.media_type = job.media_type
        model.image_paths = job.image_paths or []
        model.image_urls = job.image_urls or []

        model.audio_path = job.audio_path
        model.transcript_path = job.transcript_path
        model.transcript_text = job.transcript_text

        model.article_title = job.article_title
        model.article_body_markdown = job.article_body_markdown
        model.article_body_html = job.article_body_html
        model.article_image_prompts = job.article_image_prompts
        model.generate_inline_images = job.generate_inline_images
        model.skip_publish = job.skip_publish

        model.image_path = job.image_path
        model.wechat_image_map = job.wechat_image_map
        model.article_html = job.article_html
        model.wechat_html_path = job.wechat_html_path

        model.draft_media_id = job.draft_media_id
        model.draft_preview_url = job.draft_preview_url
        model.updated_at = datetime.fromisoformat(job.updated_at)

    def create(self) -> PipelineJob:
        job = PipelineJob()
        with get_db_ctx() as db:
            model = PipelineJobModel(
                job_id=job.job_id,
                status=job.status.value,
                current_step=None,
                created_at=datetime.fromisoformat(job.created_at),
                updated_at=datetime.fromisoformat(job.updated_at),
            )
            self._apply_job_to_model(job, model)
            db.add(model)
        return job

    def get(self, job_id: str) -> PipelineJob | None:
        with get_db_ctx() as db:
            model = db.scalar(
                select(PipelineJobModel).where(PipelineJobModel.job_id == job_id)
            )
            if not model:
                return None
            # 触发 relationship 加载，避免 session 关闭后懒加载失败。
            _ = list(model.steps)
            return self._model_to_job(model)

    def save(self, job: PipelineJob) -> None:
        job.updated_at = datetime.now().isoformat()
        with get_db_ctx() as db:
            model = db.scalar(
                select(PipelineJobModel).where(PipelineJobModel.job_id == job.job_id)
            )
            if not model:
                model = PipelineJobModel(job_id=job.job_id)
                db.add(model)

            self._apply_job_to_model(job, model)

            db.execute(
                delete(PipelineStepModel).where(PipelineStepModel.job_id == job.job_id)
            )
            db.flush()
            for step in job.steps:
                db.add(self._step_to_model(job.job_id, step))

    def list_all(self) -> list[PipelineJob]:
        with get_db_ctx() as db:
            models = db.scalars(
                select(PipelineJobModel).order_by(PipelineJobModel.created_at.desc())
            ).all()
            for model in models:
                _ = list(model.steps)
            return [self._model_to_job(model) for model in models]

    @staticmethod
    def _collect_artifact_paths(job: PipelineJob) -> list[Path]:
        """收集任务产生的所有物理文件路径，用于删除时清理磁盘。"""
        paths: list[Path] = []

        # Step1 产物：视频
        if job.video_path:
            paths.append(Path(job.video_path))

        # Step1 产物：Instagram 多图
        if job.image_paths:
            for p in job.image_paths:
                if p:
                    paths.append(Path(p))

        # Step2 产物：音频
        if job.audio_path:
            paths.append(Path(job.audio_path))

        # Step3 产物：转写文本
        if job.transcript_path:
            paths.append(Path(job.transcript_path))

        # Step5 产物：封面图
        if job.image_path:
            paths.append(Path(job.image_path))

        # Step5 产物：wechat_image_map 中所有本地图片
        if job.wechat_image_map:
            for _img_id, info in job.wechat_image_map.items():
                if isinstance(info, dict) and info.get("local_path"):
                    paths.append(Path(info["local_path"]))

        # Step6 产物：微信 HTML
        if job.wechat_html_path:
            paths.append(Path(job.wechat_html_path))

        return paths

    @staticmethod
    def _safe_delete_file(path: Path, max_retries: int = 5) -> bool:
        """
        安全删除单个文件（Windows 友好）。

        Windows 上文件可能被其他进程（yt-dlp 子进程、ffmpeg 等）短暂占用，
        单次 unlink 必定失败。本方法采用递增等待重试策略：
          - 重试间隔：0.1s → 0.2s → 0.3s → 0.5s → 0.9s（总等待 ~2s）
          - 最终回退到 os.remove()（有时能在 Path.unlink() 失败时成功）

        Args:
            path: 要删除的文件路径
            max_retries: 最大重试次数（默认 5）

        Returns:
            True=删除成功, False=删除失败
        """
        if not path.exists():
            return True  # 文件已不存在，视为成功

        if not path.is_file():
            logger.warning(f"[safe_delete] 跳过非文件: {path}")
            return False

        # 递增等待间隔序列
        delays = [0.1, 0.2, 0.3, 0.5, 0.9][:max_retries]

        for attempt in range(max_retries + 1):
            try:
                path.unlink()
                return True
            except PermissionError:
                if attempt < max_retries:
                    wait = delays[attempt]
                    logger.debug(
                        f"[safe_delete] 文件被占用，{wait:.1f}s 后重试 "
                        f"({attempt + 1}/{max_retries}): {path.name}"
                    )
                    time.sleep(wait)
                continue
            except Exception as e:
                logger.warning(f"[safe_delete] 删除异常 {path}: {e}")
                return False

        # 所有重试都失败，最后用 os.remove 试一次
        try:
            os.remove(str(path))
            logger.info(f"[safe_delete] os.remove() 成功: {path.name}")
            return True
        except Exception as e:
            logger.error(
                f"[safe_delete] 删除失败（已重试 {max_retries} 次）: {path}\n"
                f"  原因: {e}\n"
                f"  提示: 文件可能仍被其他进程占用，请稍后手动清理"
            )
            return False

    def delete(self, job_id: str) -> bool:
        """
        删除任务及其所有关联的物理文件。

        Returns:
            True=数据库记录已删除（物理文件可能部分清理失败）,
            False=任务不存在
        """
        # 1. 先读取 job，收集所有关联文件路径
        job = self.get(job_id)
        artifact_paths = self._collect_artifact_paths(job) if job else []

        # 2. 删除数据库记录
        with get_db_ctx() as db:
            model = db.scalar(
                select(PipelineJobModel).where(PipelineJobModel.job_id == job_id)
            )
            if not model:
                return False
            db.delete(model)

        # 3. 清理物理文件（数据库删除成功后）
        if not artifact_paths:
            return True

        deleted: list[str] = []
        failed: list[str] = []
        for p in artifact_paths:
            if self._safe_delete_file(p):
                deleted.append(str(p))
            else:
                failed.append(str(p))

        if deleted:
            logger.info(f"[delete job {job_id}] 已删除 {len(deleted)} 个文件")
        if failed:
            logger.warning(
                f"[delete job {job_id}] {len(failed)} 个文件删除失败（可能被占用）:\n"
                + "\n".join(f"  - {f}" for f in failed)
            )

        return True


# 全局单例
pipeline_store = PipelineStore()


# ── 暂停信号注册表（内存级即时通知）───────────────────────────────────────────
# 每个 job_id 对应一个 threading.Event，set() = 已暂停，clear() = 已恢复。
# 后台任务在执行耗时操作时可以快速检测，无需查数据库。

_pause_events: dict[str, threading.Event] = {}


def pause_signal(job_id: str) -> threading.Event:
    """获取或创建指定 job 的暂停信号 Event。"""
    if job_id not in _pause_events:
        _pause_events[job_id] = threading.Event()
    return _pause_events[job_id]


def set_pause_signal(job_id: str) -> None:
    """设置暂停信号（前端点击暂停时调用）。"""
    pause_signal(job_id).set()


def clear_pause_signal(job_id: str) -> None:
    """清除暂停信号（前端点击继续时调用）。"""
    pause_signal(job_id).clear()


def is_paused(job_id: str) -> bool:
    """检查是否已暂停（内存级，O(1)，无需查 DB）。"""
    return pause_signal(job_id).is_set()


def remove_pause_signal(job_id: str) -> None:
    """删除暂停信号（任务完成后清理）。"""
    _pause_events.pop(job_id, None)
