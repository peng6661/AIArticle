"""
分步执行 API
新流程：
  Step4 → AI JSON 结构化生成文章（Function Calling），得到 title + content(占位符HTML) + image_prompts
  Step5 → 并发生图 + 并发上传微信素材，得到 wechat_image_map
  Step6 → 替换占位符 + 微信 HTML 白名单清洗，保存文件
  Step7 → 上传封面图（第一张图）+ 发布草稿 + 打开浏览器
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File

from app.core.config import get_settings
from app.core.pipeline import (
    JobStatus, PipelineJob, StepName, StepResult, pipeline_store,
    set_pause_signal, clear_pause_signal, is_paused, remove_pause_signal,
)
from app.api._pipeline_utils import (
    detect_platform, download_video_from_url, download_image_from_url,
    SUPPORTED_PLATFORMS,
)
from app.schemas.pipeline import (
    BatchDeleteJobsRequest, BatchDeleteJobsResponse,
    ConvertHtmlRequest, ConvertHtmlResponse,
    DownloadRequest, DownloadResponse,
    ExtractAudioRequest, ExtractAudioResponse,
    GenerateArticleRequest, GenerateArticleResponse,
    GenerateImageRequest, GenerateImageResponse,
    JobStatusResponse, StepResultSchema,
    PauseJobResponse,
    PublishDraftRequest, PublishDraftResponse,
    ResumeJobRequest,
    RetryJobRequest, RetryJobResponse,
    TranscribeRequest, TranscribeResponse,
    UploadVideoResponse,
)

router = APIRouter(prefix="/pipeline", tags=["Pipeline 分步执行"])
cfg = get_settings()

# ── 本地别名（保持文件内部调用不变）───────────────────────────────────────────
_download_video_from_url = download_video_from_url
_download_image_from_url = download_image_from_url


def _get_job_or_404(job_id: str) -> PipelineJob:
    job = pipeline_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"job_id 不存在: {job_id}")
    return job


def _remove_step_result(job: PipelineJob, step: StepName) -> None:
    """移除指定步骤的历史 StepResult（用于重试）"""
    job.steps = [s for s in job.steps if s.step != step]
    pipeline_store.save(job)


def _check_job_alive(job_id: str) -> PipelineJob:
    """检查任务是否仍存在且可执行，否则静默返回。

    用于后台 _run_xxx 函数开头，确保任务未被删除/取消/暂停。
    如果任务已不可执行，返回 None（调用方应直接 return）。
    优先使用内存级信号检测（即时），再回退到 DB 检测。
    """
    # 内存级检测（O(1)，无需查 DB）
    if is_paused(job_id):
        return None
    job = pipeline_store.get(job_id)
    if job is None:
        return None  # 已删除
    if job.status in (JobStatus.PAUSED, JobStatus.CANCELLED):
        return None  # 已暂停/取消
    return job


def _begin_step(job: PipelineJob, step: StepName, retry: bool = False) -> StepResult:
    """开始一个步骤。retry=True 时会先清除该步骤旧结果。

    如果 job 已被暂停、取消或删除，抛出异常中断后续步骤执行。
    优先使用内存级信号检测（即时感知暂停）。
    """
    # 内存级即时检测
    if is_paused(job.job_id):
        raise RuntimeError("任务已被暂停，不再继续执行后续步骤")

    # 从数据库重新读取最新状态，避免内存缓存过期
    fresh = pipeline_store.get(job.job_id)
    if fresh is None:
        raise RuntimeError("任务已被删除，不再继续执行后续步骤")
    if fresh.status == JobStatus.PAUSED:
        raise RuntimeError("任务已被暂停，不再继续执行后续步骤")
    if fresh.status == JobStatus.CANCELLED:
        raise RuntimeError("任务已被取消，不再继续执行后续步骤")

    # 同步内存对象的状态（使用数据库中的最新值，而非强制覆盖为 RUNNING）
    job.status = fresh.status

    if retry:
        _remove_step_result(job, step)
    result = StepResult(step=step, status=JobStatus.RUNNING)
    job.current_step = step
    # 重试时清除之前的错误标记
    if retry:
        job.error = None
    job.steps.append(result)
    pipeline_store.save(job)
    return result


def _finish_step(job: PipelineJob, result: StepResult, data: dict = None, message: str = "完成"):
    """标记步骤完成并保存。

    保存前会从数据库重新检查任务状态，如果已被暂停/取消/删除，
    则不保存并抛出 RuntimeError，让调用方优雅退出。
    同时检查内存级暂停信号（即时感知）。
    """
    # 内存级即时检测
    if is_paused(job.job_id):
        raise RuntimeError("任务已被暂停，不再继续执行后续步骤")

    # 保存前再次检查，防止 _begin_step → 执行耗时操作 → 之间用户点了暂停
    fresh = pipeline_store.get(job.job_id)
    if fresh is None:
        raise RuntimeError("任务已被删除，不再继续执行后续步骤")
    if fresh.status == JobStatus.PAUSED:
        raise RuntimeError("任务已被暂停，不再继续执行后续步骤")
    if fresh.status == JobStatus.CANCELLED:
        raise RuntimeError("任务已被取消，不再继续执行后续步骤")

    result.status = JobStatus.SUCCESS
    result.message = message
    result.data = data or {}
    result.finished_at = datetime.now().isoformat()

    # 同步数据库最新状态到内存对象再保存，避免覆盖 PAUSED
    job.status = fresh.status
    pipeline_store.save(job)


def _fail_step(job: PipelineJob, result: StepResult, error: str):
    result.status = JobStatus.FAILED
    result.message = error
    result.finished_at = datetime.now().isoformat()
    job.status = JobStatus.FAILED
    job.error = error
    pipeline_store.save(job)


def _job_to_schema(job: PipelineJob) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        current_step=job.current_step,
        steps=[
            StepResultSchema(
                step=s.step, status=s.status, message=s.message,
                data=s.data, started_at=s.started_at, finished_at=s.finished_at,
            )
            for s in job.steps
        ],
        skip_publish=job.skip_publish,
        share_text=job.share_text,
        video_path=job.video_path,
        audio_path=job.audio_path,
        transcript_path=job.transcript_path,
        article_body_markdown=job.article_body_markdown,
        article_html=(
            job.article_html[:500] + "..."
            if job.article_html and len(job.article_html) > 500
            else job.article_html
        ),
        wechat_html_path=job.wechat_html_path,
        image_path=job.image_path,
        # Instagram 多图帖子支持
        media_type=job.media_type,
        image_count=len(job.image_paths) if job.image_paths else 0,
        image_paths=job.image_paths,
        image_urls=job.image_urls,
        draft_media_id=job.draft_media_id,
        draft_preview_url=job.draft_preview_url,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _get_latest_failed_step(job: PipelineJob) -> StepResult | None:
    for step in reversed(job.steps):
        if step.status == JobStatus.FAILED:
            return step
    return None


def _require_api_key(api_key: str) -> str:
    resolved = (api_key or "").strip()
    if not resolved:
        raise HTTPException(status_code=400, detail="重试该步骤需要 SiliconFlow API Key")
    return resolved


def _schedule_retry_for_failed_step(
    background_tasks: BackgroundTasks,
    job: PipelineJob,
    failed_step: StepResult,
    req: RetryJobRequest,
) -> StepName:
    step_name = failed_step.step
    ai_cfg = cfg.get_ai_provider_config(req.ai_provider)

    if step_name == StepName.DOWNLOAD:
        if not job.share_text:
            raise HTTPException(status_code=400, detail="缺少原始分享链接，无法重试下载")
        background_tasks.add_task(_run_download, job.job_id, job.share_text, retry=True)
    elif step_name == StepName.EXTRACT_AUDIO:
        background_tasks.add_task(_run_extract_audio, job.job_id, cfg.audio_default_format, True)
    elif step_name == StepName.TRANSCRIBE:
        background_tasks.add_task(
            _run_transcribe,
            job.job_id,
            cfg.transcribe_default_model,
            cfg.transcribe_default_language,
            None,  # device: 重试时走 config 默认值
            None,  # compute_type: 重试时走 config 默认值
            True,
        )
    elif step_name == StepName.GENERATE_ARTICLE:
        background_tasks.add_task(
            _run_generate_article,
            job.job_id,
            _require_api_key(req.api_key),
            "",
            "",
            req.text_model or ai_cfg["default_text_model"],
            ai_cfg["default_temperature"],
            job.generate_inline_images,
            True,
            ai_cfg["base_url"],
            ai_cfg["max_tokens"],
        )
    elif step_name == StepName.GENERATE_IMAGE:
        background_tasks.add_task(
            _run_generate_image,
            job.job_id,
            _require_api_key(req.api_key),
            req.wechat_appid,
            req.wechat_appsecret,
            req.image_model or ai_cfg["default_image_model"],
            ai_cfg["default_image_size"],
            job.generate_inline_images,
            True,
            ai_cfg["base_url"],
        )
    elif step_name == StepName.CONVERT_HTML:
        background_tasks.add_task(_run_convert_html, job.job_id, True)
    elif step_name == StepName.PUBLISH_DRAFT:
        appid = req.wechat_appid or cfg.wechat_appid
        appsecret = req.wechat_appsecret or cfg.wechat_appsecret
        if not appid or not appsecret:
            raise HTTPException(status_code=400, detail="重试发布需要公众号 AppID 和 AppSecret")
        background_tasks.add_task(
            _run_publish_draft,
            job.job_id,
            appid,
            appsecret,
            "",
            "",
            "",
            "",
            "",
            True,
        )
    else:
        raise HTTPException(status_code=400, detail=f"暂不支持重试步骤: {step_name}")

    return step_name


# ── 状态查询 ────────────────────────────────────────────────────────────────

@router.get("/jobs", summary="列出所有 Job")
def list_jobs():
    jobs = pipeline_store.list_all()
    return {"total": len(jobs), "jobs": [_job_to_schema(j) for j in jobs]}


@router.get("/jobs/{job_id}", response_model=JobStatusResponse, summary="查询 Job 状态")
def get_job_status(job_id: str):
    return _job_to_schema(_get_job_or_404(job_id))


@router.delete("/jobs/{job_id}", summary="删除 Job")
def delete_job(job_id: str):
    job = pipeline_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job 不存在")
    # 运行中/等待中的任务：先标记为 CANCELLED，后台任务会在下一步开始时检测到并退出
    if job.status in (JobStatus.RUNNING, JobStatus.PENDING):
        job.status = JobStatus.CANCELLED
        pipeline_store.save(job)
    if pipeline_store.delete(job_id):
        return {"message": f"Job {job_id} 已删除"}
    raise HTTPException(status_code=500, detail="删除失败")


@router.post("/jobs/batch-delete", response_model=BatchDeleteJobsResponse, summary="批量删除 Job")
async def batch_delete_jobs(req: BatchDeleteJobsRequest):
    job_ids = [job_id for job_id in req.job_ids if job_id]
    if not job_ids:
        raise HTTPException(status_code=400, detail="请至少传入一个 job_id")

    # 先将运行中/等待中的任务标记为 CANCELLED
    for job_id in job_ids:
        job = pipeline_store.get(job_id)
        if job and job.status in (JobStatus.RUNNING, JobStatus.PENDING):
            job.status = JobStatus.CANCELLED
            pipeline_store.save(job)

    deleted_job_ids: list[str] = []
    for job_id in job_ids:
        if pipeline_store.delete(job_id):
            deleted_job_ids.append(job_id)

    if not deleted_job_ids:
        raise HTTPException(status_code=404, detail="未找到可删除的任务")

    return BatchDeleteJobsResponse(
        success=True,
        message=f"已删除 {len(deleted_job_ids)} 条任务",
        deleted_count=len(deleted_job_ids),
        deleted_job_ids=deleted_job_ids,
    )


@router.post("/jobs/{job_id}/retry", response_model=RetryJobResponse, summary="重试 Job 最近失败的步骤")
async def retry_failed_job(job_id: str, req: RetryJobRequest, background_tasks: BackgroundTasks):
    job = _get_job_or_404(job_id)
    if job.status != JobStatus.FAILED:
        raise HTTPException(status_code=400, detail="只有失败状态的任务才可重试")

    failed_step = _get_latest_failed_step(job)
    if not failed_step:
        raise HTTPException(status_code=400, detail="当前任务没有可重试的失败步骤")

    # 清理可能残留的暂停信号，确保重试从干净状态开始
    clear_pause_signal(job_id)
    # 将状态改为 RUNNING，使前端 canPause 条件成立，暂停按钮可见
    job.status = JobStatus.RUNNING
    job.error = None
    pipeline_store.save(job)

    retried_step = _schedule_retry_for_failed_step(background_tasks, job, failed_step, req)
    return RetryJobResponse(
        success=True,
        message=f"已提交重试：{retried_step}",
        job_id=job.job_id,
        retried_step=retried_step,
    )




# ── 暂停任务 ──────────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/pause", response_model=PauseJobResponse, summary="暂停正在运行的任务")
async def pause_job(job_id: str):
    job = _get_job_or_404(job_id)
    if job.status not in (JobStatus.RUNNING, JobStatus.PENDING):
        raise HTTPException(
            status_code=400,
            detail=f"只有运行中或等待中的任务才能暂停（当前状态: {job.status.value}）",
        )
    # 设置内存级暂停信号（后台线程可即时感知）
    set_pause_signal(job_id)
    # 持久化到数据库
    job.status = JobStatus.PAUSED
    pipeline_store.save(job)
    return PauseJobResponse(
        success=True,
        message=f"任务 {job_id} 已暂停",
        job_id=job_id,
    )


# ── 继续任务 ──────────────────────────────────────────────────────────────

def _schedule_resume_for_remaining_steps(
    background_tasks: BackgroundTasks,
    job: PipelineJob,
    req: ResumeJobRequest,
) -> StepName | None:
    """根据已完成的步骤，从第一个未完成的步骤开始调度后续所有步骤。"""

    completed_steps = {s.step for s in job.steps if s.status == JobStatus.SUCCESS}
    remaining = [s for s in StepName if s not in completed_steps]

    if not remaining:
        return None  # 所有步骤已完成

    first = remaining[0]
    ai_cfg = cfg.get_ai_provider_config(req.ai_provider)

    if first == StepName.DOWNLOAD:
        if not job.share_text:
            raise HTTPException(status_code=400, detail="缺少原始分享链接，无法继续")
        background_tasks.add_task(_run_download, job.job_id, job.share_text)
    elif first == StepName.EXTRACT_AUDIO:
        background_tasks.add_task(_run_extract_audio, job.job_id, cfg.audio_default_format)
    elif first == StepName.TRANSCRIBE:
        background_tasks.add_task(
            _run_transcribe,
            job.job_id,
            cfg.transcribe_default_model,
            cfg.transcribe_default_language,
            None,
            None,
        )
    elif first == StepName.GENERATE_ARTICLE:
        background_tasks.add_task(
            _run_generate_article,
            job.job_id,
            _require_api_key(req.api_key),
            "",
            "",
            req.text_model or ai_cfg["default_text_model"],
            ai_cfg["default_temperature"],
            job.generate_inline_images,
            False,
            ai_cfg["base_url"],
            ai_cfg["max_tokens"],
        )
    elif first == StepName.GENERATE_IMAGE:
        background_tasks.add_task(
            _run_generate_image,
            job.job_id,
            _require_api_key(req.api_key),
            req.wechat_appid,
            req.wechat_appsecret,
            req.image_model or ai_cfg["default_image_model"],
            ai_cfg["default_image_size"],
            job.generate_inline_images,
            False,
            ai_cfg["base_url"],
        )
    elif first == StepName.CONVERT_HTML:
        background_tasks.add_task(_run_convert_html, job.job_id)
    elif first == StepName.PUBLISH_DRAFT:
        appid = req.wechat_appid or cfg.wechat_appid
        appsecret = req.wechat_appsecret or cfg.wechat_appsecret
        if not appid or not appsecret:
            raise HTTPException(status_code=400, detail="继续发布步骤需要公众号 AppID 和 AppSecret")
        background_tasks.add_task(
            _run_publish_draft,
            job.job_id,
            appid,
            appsecret,
            "",
            "",
            "",
            "",
            "",
        )
    else:
        raise HTTPException(status_code=400, detail=f"未知的步骤: {first}")

    return first


@router.post("/jobs/{job_id}/resume", summary="继续已暂停的任务")
async def resume_job(job_id: str, req: ResumeJobRequest, background_tasks: BackgroundTasks):
    job = _get_job_or_404(job_id)
    if job.status != JobStatus.PAUSED:
        raise HTTPException(
            status_code=400,
            detail=f"只有暂停状态的任务才能继续（当前状态: {job.status.value}）",
        )

    # 清除内存级暂停信号
    clear_pause_signal(job_id)

    # 先将状态改为 RUNNING，否则 _begin_step 会因 PAUSED 状态抛异常
    job.status = JobStatus.RUNNING
    pipeline_store.save(job)

    first_step = _schedule_resume_for_remaining_steps(background_tasks, job, req)
    if not first_step:
        # 所有步骤已完成，直接标记成功
        job.status = JobStatus.SUCCESS
        pipeline_store.save(job)
        return {
            "success": True,
            "message": "所有步骤已完成，任务已标记为成功",
            "job_id": job_id,
            "resumed_step": None,
        }

    return {
        "success": True,
        "message": f"任务已从「{first_step.value}」步骤继续执行",
        "job_id": job_id,
        "resumed_step": first_step.value,
    }


# ── 视频上传（跳过 Step1，从 Step2 开始）─────────────────────────────────────

@router.post("/upload-video", response_model=UploadVideoResponse, summary="上传本地视频，跳过下载步骤，直接从提取音频开始")
async def upload_video(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(..., description="视频文件（mp4/mov/avi/mkv/webm）"),
):
    # 校验文件类型
    allowed_extensions = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv"}
    suffix = Path(video.filename or "").suffix.lower()
    if suffix not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {suffix}，支持: {', '.join(sorted(allowed_extensions))}",
        )

    # 校验文件大小（最大 2GB）
    MAX_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB
    if video.size and video.size > MAX_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大 ({video.size / 1024 / 1024:.1f} MB)，最大支持 2 GB",
        )

    # 生成安全的文件名，保存到 downloads_dir
    cfg.downloads_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(video.filename or "uploaded_video").stem
    # 去掉不安全字符
    safe_name = "".join(c for c in safe_name if c.isalnum() or c in "-_ ").strip()
    safe_name = safe_name[:80] or "uploaded_video"
    dest_path = cfg.downloads_dir / f"{safe_name}{suffix}"

    # 避免重名
    counter = 1
    while dest_path.exists():
        dest_path = cfg.downloads_dir / f"{safe_name}_{counter}{suffix}"
        counter += 1

    # 创建 Job
    job = pipeline_store.create()
    job.share_text = f"[本地上传] {video.filename or 'video'}"
    job.media_type = "video"
    pipeline_store.save(job)

    # 后台执行：保存文件 + 标记 Step1 完成 + 触发 Step2
    background_tasks.add_task(
        _run_upload_video,
        job.job_id,
        video,
        dest_path,
    )

    return UploadVideoResponse(
        success=True,
        message=f"视频上传成功，点击「免费生成」开始处理",
        job_id=job.job_id,
    )


def _run_upload_video(job_id: str, video_file: UploadFile, dest_path: Path):
    """后台任务：保存上传文件 → 标记 Step1 完成 → 暂停等待用户触发后续步骤。"""
    import shutil

    try:
        job = pipeline_store.get(job_id)
        if not job:
            return

        # ── Step1: 标记为"上传完成"（虚拟完成） ──
        result = StepResult(
            step=StepName.DOWNLOAD,
            status=JobStatus.RUNNING,
        )
        job.current_step = StepName.DOWNLOAD
        job.steps.append(result)
        pipeline_store.save(job)

        # 保存上传的文件
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(video_file.file, f)

        job.video_path = str(dest_path.resolve())
        job.media_type = "video"

        # 标记 Step1 完成
        result.status = JobStatus.SUCCESS
        result.message = "本地上传完成"
        result.data = {
            "video_path": str(dest_path.resolve()),
            "title": dest_path.stem,
            "platform": "local_upload",
            "media_type": "video",
        }
        result.finished_at = datetime.now().isoformat()

        # 设为 PAUSED，等待用户点击"免费生成"后 resume
        job.status = JobStatus.PAUSED
        pipeline_store.save(job)

    except Exception as e:
        _fail_step(job, result, f"视频保存失败: {e}")


# ── Step 1: 全平台视频下载 ──────────────────────────────────────────────────

@router.post("/step/download", response_model=DownloadResponse, summary="Step1: 下载视频（支持全平台）")
async def step_download(req: DownloadRequest, background_tasks: BackgroundTasks):
    # 支持重试：如果传了 job_id 且 job 存在，走重试逻辑
    if req.job_id:
        job = _get_job_or_404(req.job_id)
        # 检查该步骤是否可重试（必须处于 failed 状态且有失败的 download 步骤）
        failed_download = any(
            s.step == StepName.DOWNLOAD and s.status == JobStatus.FAILED
            for s in job.steps
        )
        if not failed_download:
            raise HTTPException(status_code=400, detail="该步骤不可重试（仅支持重试失败的步骤）")
        clear_pause_signal(req.job_id)
        job.status = JobStatus.RUNNING
        job.error = None
        pipeline_store.save(job)
        background_tasks.add_task(_run_download, req.job_id, req.share_text, retry=True)
        return DownloadResponse(success=True, message="下载重试任务已提交", job_id=req.job_id)
    
    # 首次执行
    job = pipeline_store.create()
    job.share_text = req.share_text
    pipeline_store.save(job)
    background_tasks.add_task(_run_download, job.job_id, req.share_text)
    return DownloadResponse(success=True, message="下载任务已提交", job_id=job.job_id)


def _run_download(job_id: str, share_text: str, retry: bool = False):
    from app.services.douyin_download_service import DouyinExtractor
    from app.services.instagram_download_service import InstagramExtractor
    from app.services.bilibili_download_service import BilibiliExtractor
    from app.services.tiktok_download_service import TikTokExtractor
    from app.services.kuaishou_download_service import KuaishouExtractor
    from app.services.x_download_service import XVideoExtractor
    from app.services.youtube_download_service import YouTubeExtractor

    job = _check_job_alive(job_id)
    if not job:
        return
    job.share_text = share_text
    result = _begin_step(job, StepName.DOWNLOAD, retry=retry)
    try:
        platform = detect_platform(share_text)

        if platform == "douyin":
            extractor = DouyinExtractor()
            video_data = extractor.extract(share_text)
            if not video_data or video_data.get("error"):
                raise ValueError("无法从分享文本中提取视频链接，请检查输入")
            # 新版 extract() 返回统一格式，用通用下载函数替代旧版 download_video()
            video_url = video_data.get("video_url") or video_data.get("url", "")
            if not video_url:
                raise ValueError("抖音解析成功但未获取到下载地址")
            title = video_data.get("title") or "douyin_video"
            video_path = _download_video_from_url(
                video_url=video_url,
                save_dir=cfg.downloads_dir,
                filename=title,
                platform="douyin",
            )
            job.video_path = str(video_path)
            _finish_step(job, result, data={"video_path": str(video_path), "title": title, "platform": "douyin"})
            
        elif platform == "instagram":
            extractor = InstagramExtractor()
            media_data = extractor.extract(share_text)
            if not media_data or media_data.get("error"):
                raise ValueError("无法解析 Instagram 链接，请检查输入或确认内容可访问（可能需要登录）")

            title = media_data.get("title") or "Instagram media"
            images = media_data.get("images", [])
            video_url = media_data.get("video_url") or media_data.get("url", "")

            if images and len(images) > 0:
                # 图片/轮播帖子：逐张下载
                import requests as _req
                downloaded_paths = []
                for idx, img in enumerate(images):
                    # 内存级暂停检测（循环内部即时响应）
                    if is_paused(job.job_id):
                        raise RuntimeError("任务已被暂停，停止下载")
                    img_url = img.get("url") or img.get("display_url", "")
                    if not img_url:
                        continue
                    img_filename = f"{title}_{idx+1}"
                    img_path = _download_image_from_url(img_url, cfg.downloads_dir, img_filename)
                    downloaded_paths.append(str(img_path))

                if not downloaded_paths:
                    raise ValueError("Instagram 图片下载失败")

                image_urls = [img.get("url") or img.get("display_url", "") for img in images if isinstance(img, dict)]
                job.video_path = str(downloaded_paths[0])
                job.image_paths = downloaded_paths
                job.image_urls = image_urls
                _finish_step(job, result, data={
                    "video_path": str(downloaded_paths[0]),
                    "title": title,
                    "platform": "instagram",
                    "media_type": "image",
                    "image_count": len(downloaded_paths),
                    "image_paths": downloaded_paths,
                    "image_urls": image_urls,
                })
            elif video_url:
                # 视频帖子
                video_path = _download_video_from_url(
                    video_url=video_url,
                    save_dir=cfg.downloads_dir,
                    filename=title,
                    platform="instagram",
                )
                job.video_path = str(video_path)
                _finish_step(job, result, data={
                    "video_path": str(video_path),
                    "title": title,
                    "platform": "instagram",
                    "media_type": "video",
                })
            else:
                raise ValueError("Instagram 解析成功但未获取到任何媒体地址")

        elif platform in ("bilibili", "tiktok", "kuaishou", "x", "youtube"):
            # 通用平台：extract() → 直链下载
            platform_map = {
                "bilibili": (BilibiliExtractor, "B站"),
                "tiktok": (TikTokExtractor, "TikTok"),
                "kuaishou": (KuaishouExtractor, "快手"),
                "x": (XVideoExtractor, "X(Twitter)"),
                "youtube": (YouTubeExtractor, "YouTube"),
            }
            ExtractorClass, platform_name = platform_map[platform]
            extractor = ExtractorClass()
            media_data = extractor.extract(share_text)
            if not media_data:
                raise ValueError(f"无法解析 {platform_name} 链接，请检查链接是否有效")

            title = media_data.get("title") or f"{platform_name}_video"

            # ── YouTube 特殊处理：CDN 直链有时效性，必须用 yt-dlp 直接下载 ──
            if platform == "youtube":
                # 将原始 URL 存入 media_data 供 download() 使用
                media_data["_original_url"] = share_text
                downloaded = extractor.download(media_data, save_dir=cfg.downloads_dir)
                if not downloaded:
                    raise ValueError("YouTube 视频下载失败，请检查链接是否有效或稍后重试")
                job.video_path = str(downloaded)
                _finish_step(job, result, data={
                    "video_path": str(downloaded),
                    "title": title,
                    "platform": platform,
                })
            else:
                # 其他平台：extract() → 直链 → requests 下载
                video_url = media_data.get("video_url") or media_data.get("url", "")
                if not video_url:
                    raise ValueError(f"{platform_name} 未获取到有效的视频下载地址")

                video_path = _download_video_from_url(
                    video_url=video_url,
                    save_dir=cfg.downloads_dir,
                    filename=title,
                    platform=platform,
                )
                job.video_path = str(video_path)
                _finish_step(job, result, data={
                    "video_path": str(video_path),
                    "title": title,
                    "platform": platform,
                })

        else:
            raise ValueError(f"无法识别的链接平台，支持：{SUPPORTED_PLATFORMS}")
            
    except Exception as e:
        _fail_step(job, result, str(e))


# ── Step 2: 提取音频 ────────────────────────────────────────────────────────

@router.post("/step/extract_audio", response_model=ExtractAudioResponse, summary="Step2: 提取音频")
async def step_extract_audio(req: ExtractAudioRequest, background_tasks: BackgroundTasks):
    job = _get_job_or_404(req.job_id)
    if not job.video_path:
        raise HTTPException(status_code=400, detail="请先完成 Step1（下载视频）")
    
    # 检查重试条件
    failed_step = any(
        s.step == StepName.EXTRACT_AUDIO and s.status == JobStatus.FAILED
        for s in job.steps
    )
    if not failed_step and job.status == JobStatus.FAILED:
        # 非 extract_audio 步骤失败，不允许直接跳步
        raise HTTPException(status_code=400, detail="当前 Job 有其他步骤失败，请先重试失败的步骤")
    
    if failed_step:
        clear_pause_signal(req.job_id)
        job.status = JobStatus.RUNNING
        job.error = None
        pipeline_store.save(job)
    background_tasks.add_task(_run_extract_audio, req.job_id, req.audio_format, retry=failed_step)
    return ExtractAudioResponse(success=True, message="音频提取任务已提交" + ("（重试）" if failed_step else ""), job_id=req.job_id)


def _run_extract_audio(job_id: str, audio_format: str, retry: bool = False):
    from app.services.audio_service import extract_audio
    job = _check_job_alive(job_id)
    if not job:
        return
    result = _begin_step(job, StepName.EXTRACT_AUDIO, retry=retry)
    try:
        audio_path = extract_audio(Path(job.video_path), audio_format=audio_format)
        job.audio_path = str(audio_path)
        _finish_step(job, result, data={"audio_path": str(audio_path)})
    except Exception as e:
        _fail_step(job, result, str(e))


# ── Step 3: 语音转写 ────────────────────────────────────────────────────────

@router.post("/step/transcribe", response_model=TranscribeResponse, summary="Step3: 语音转写")
async def step_transcribe(req: TranscribeRequest, background_tasks: BackgroundTasks):
    job = _get_job_or_404(req.job_id)
    if not job.audio_path:
        raise HTTPException(status_code=400, detail="请先完成 Step2（提取音频）")
    
    failed_step = any(
        s.step == StepName.TRANSCRIBE and s.status == JobStatus.FAILED
        for s in job.steps
    )
    if not failed_step and job.status == JobStatus.FAILED:
        raise HTTPException(status_code=400, detail="当前 Job 有其他步骤失败，请先重试失败的步骤")
    
    if failed_step:
        clear_pause_signal(req.job_id)
        job.status = JobStatus.RUNNING
        job.error = None
        pipeline_store.save(job)
    background_tasks.add_task(_run_transcribe, req.job_id, req.model_size, req.language, req.device or None, req.compute_type or None, retry=failed_step)
    return TranscribeResponse(success=True, message="转写任务已提交" + ("（重试）" if failed_step else ""), job_id=req.job_id)


def _run_transcribe(job_id: str, model_size: str, language: str, device: str = None, compute_type: str = None, retry: bool = False):
    from app.services.transcribe_service import transcribe_audio
    job = _check_job_alive(job_id)
    if not job:
        return
    result = _begin_step(job, StepName.TRANSCRIBE, retry=retry)
    try:
        audio_path = Path(job.audio_path)
        transcript_path = audio_path.with_suffix(".txt")
        text = transcribe_audio(
            audio_path=audio_path, output_path=transcript_path,
            model_size=model_size, language=language,
            device=device, compute_type=compute_type,
        )
        job.transcript_path = str(transcript_path)
        job.transcript_text = text
        _finish_step(job, result, data={"transcript_path": str(transcript_path), "preview": text[:200]})
    except Exception as e:
        _fail_step(job, result, str(e))


# ── Step 4: 生成文章（JSON 结构化输出）────────────────────────────────────────

@router.post("/step/generate_article", response_model=GenerateArticleResponse, summary="Step4: AI 生成文章（JSON）")
async def step_generate_article(req: GenerateArticleRequest, background_tasks: BackgroundTasks):
    job = _get_job_or_404(req.job_id)
    if not job.transcript_path:
        raise HTTPException(status_code=400, detail="请先完成 Step3（语音转写）")

    failed_step = any(
        s.step == StepName.GENERATE_ARTICLE and s.status == JobStatus.FAILED
        for s in job.steps
    )
    if not failed_step and job.status == JobStatus.FAILED:
        raise HTTPException(status_code=400, detail="当前 Job 有其他步骤失败，请先重试失败的步骤")

    if failed_step:
        clear_pause_signal(req.job_id)
        job.status = JobStatus.RUNNING
        job.error = None
        pipeline_store.save(job)
    ai_cfg = cfg.get_ai_provider_config(req.ai_provider)
    background_tasks.add_task(
        _run_generate_article,
        req.job_id, req.api_key, req.topic,
        req.extra_requirements,
        req.text_model or ai_cfg["default_text_model"],
        req.temperature,
        req.generate_inline_images, retry=failed_step,
        base_url=ai_cfg["base_url"],
        max_tokens=ai_cfg["max_tokens"],
        rag_collection=req.rag_collection,
        rag_top_k=req.rag_top_k,
        rag_embedding_model=req.rag_embedding_model,
        rag_embedding_provider=req.rag_embedding_provider,
    )
    return GenerateArticleResponse(success=True, message="文章生成任务已提交" + ("（重试）" if failed_step else ""), job_id=req.job_id)


def _run_generate_article(job_id, api_key, topic, extra_requirements, text_model, temperature, generate_inline_images=True, retry: bool = False, base_url: str | None = None, max_tokens: int | None = None, rag_collection: str = "", rag_top_k: int = 5, rag_embedding_model: str = "", rag_embedding_provider: str = ""):
    from app.services.article_service import generate_article

    # ── 打印配置信息，方便调试 ──────────────────────────────────────────────
    masked_key = (api_key[:6] + "****" + api_key[-4:]) if api_key and len(api_key) > 10 else "（空）"
    print(f"\n{'='*60}")
    print(f"[Step4-文章] 配置信息 | job_id={job_id}")
    print(f"  base_url  = {base_url}")
    print(f"  api_key   = {masked_key}")
    print(f"  model     = {text_model}")
    print(f"  temp      = {temperature}")
    print(f"  max_tokens= {max_tokens}")
    print(f"  retry     = {retry}")
    print(f"{'='*60}\n")

    job = _check_job_alive(job_id)
    if not job:
        return
    result = _begin_step(job, StepName.GENERATE_ARTICLE, retry=retry)
    try:
        # AI 返回结构化 JSON：{title, content, image_prompts}
        # generate_inline_images=True  → 正文含占位符，image_prompts 含封面+文中图
        # generate_inline_images=False → 正文无占位符，image_prompts 只有封面(id=cover)
        article_data = generate_article(
            material_path=Path(job.transcript_path),
            topic=topic or None,
            extra_requirements=extra_requirements,
            api_key=api_key,
            model_name=text_model or None,
            temperature=temperature,
            generate_inline_images=generate_inline_images,
            base_url=base_url,
            max_tokens=max_tokens,
            rag_collection=rag_collection or None,
            rag_top_k=rag_top_k,
            rag_embedding_model=rag_embedding_model or None,
            rag_embedding_provider=rag_embedding_provider or None,
        )

        job.article_title = article_data["title"]
        job.article_body_markdown = article_data["content"]
        job.article_body_html = article_data["content"]  # 临时存储，后续步骤会转换为 HTML
        job.article_image_prompts = article_data["image_prompts"]
        # 把开关存入 job，Step5/6 需要读取
        job.generate_inline_images = generate_inline_images

        prompts_summary = [
            {"id": p["id"], "prompt_preview": p["prompt"][:60]}
            for p in article_data["image_prompts"]
        ]
        _finish_step(job, result, data={
            "title": article_data["title"],
            "generate_inline_images": generate_inline_images,
            "image_count": len(article_data["image_prompts"]),
            "image_prompts": prompts_summary,
            "content_preview": article_data["content"][:300],
        })
    except Exception as e:
        _fail_step(job, result, str(e))


# ── Step 5: 并发生图 + 上传微信素材 ────────────────────────────────────────────

@router.post("/step/generate_image", response_model=GenerateImageResponse, summary="Step5: 并发生图 & 上传微信素材")
async def step_generate_image(req: GenerateImageRequest, background_tasks: BackgroundTasks):
    job = _get_job_or_404(req.job_id)
    if not job.article_image_prompts:
        raise HTTPException(status_code=400, detail="请先完成 Step4（生成文章）")

    failed_step = any(
        s.step == StepName.GENERATE_IMAGE and s.status == JobStatus.FAILED
        for s in job.steps
    )
    if not failed_step and job.status == JobStatus.FAILED:
        raise HTTPException(status_code=400, detail="当前 Job 有其他步骤失败，请先重试失败的步骤")

    if failed_step:
        clear_pause_signal(req.job_id)
        job.status = JobStatus.RUNNING
        job.error = None
        pipeline_store.save(job)
    ai_cfg = cfg.get_ai_provider_config(req.ai_provider)
    background_tasks.add_task(
        _run_generate_image,
        req.job_id, req.api_key, req.wechat_appid, req.wechat_appsecret,
        req.image_model or ai_cfg["default_image_model"],
        req.image_size or ai_cfg["default_image_size"],
        req.generate_inline_images, retry=failed_step,
        base_url=ai_cfg["base_url"],
    )
    return GenerateImageResponse(success=True, message="配图生成任务已提交" + ("（重试）" if failed_step else ""), job_id=req.job_id)


def _run_generate_image(job_id, api_key, wechat_appid, wechat_appsecret, image_model, image_size, generate_inline_images=True, retry: bool = False, base_url: str | None = None):
    from app.services.image_service import generate_images_concurrent, upload_images_to_wechat_concurrent
    from app.services.wechat_service import get_access_token

    # ── 打印配置信息，方便调试 ──────────────────────────────────────────────
    masked_key = (api_key[:6] + "****" + api_key[-4:]) if api_key and len(api_key) > 10 else "（空）"
    print(f"\n{'='*60}")
    print(f"[Step5-配图] 配置信息 | job_id={job_id}")
    print(f"  base_url  = {base_url}")
    print(f"  api_key   = {masked_key}")
    print(f"  model     = {image_model}")
    print(f"  size      = {image_size}")
    print(f"  retry     = {retry}")
    print(f"{'='*60}\n")

    job = _check_job_alive(job_id)
    if not job:
        return
    result = _begin_step(job, StepName.GENERATE_IMAGE, retry=retry)
    try:
        all_prompts = job.article_image_prompts  # 含 cover + img_01...

        # ── 1. 决定本次实际生成哪些图 ─────────────────────────────────────────
        # generate_inline_images=True  → 生成全部（封面 + 文中插图）
        # generate_inline_images=False → 仅生成封面（id=cover 或第一张）
        if generate_inline_images:
            prompts_to_generate = all_prompts
        else:
            # 只保留封面：优先 id=cover，否则取第一张
            cover_prompt = next(
                (p for p in all_prompts if p["id"] == "cover"),
                all_prompts[0] if all_prompts else None,
            )
            prompts_to_generate = [cover_prompt] if cover_prompt else []

        if not prompts_to_generate:
            raise ValueError("没有可生成的图片 prompt，请先完成 Step4")

        # ── 2. 并发生图并下载到本地 ───────────────────────────────────────────
        local_map = generate_images_concurrent(
            image_prompts=prompts_to_generate,
            api_key=api_key,
            output_dir=cfg.outputs_dir,
            model_name=image_model or None,
            image_size=image_size or None,
            base_url=base_url,
        )

        # ── 3. 封面图：优先 id=cover，兜底取 local_map 第一张 ────────────────
        cover_local_path = local_map.get("cover") or next(iter(local_map.values()), None)
        if cover_local_path:
            job.image_path = str(cover_local_path.resolve())

        # ── 4. 若开启了文中插图 且 提供了微信凭证，并发上传到微信素材库 ────────
        #      cover 图不上传为正文素材（它会在 Step7 单独作为 thumb 上传）
        appid = wechat_appid or cfg.wechat_appid
        appsecret = wechat_appsecret or cfg.wechat_appsecret

        wechat_upload_map: dict[str, dict] = {}
        if generate_inline_images and appid and appsecret:
            # 只上传文中插图（排除 cover）
            inline_map = {k: v for k, v in local_map.items() if k != "cover"}
            if inline_map:
                access_token = get_access_token(appid, appsecret)
                wechat_upload_map = upload_images_to_wechat_concurrent(
                    local_image_map=inline_map,
                    access_token=access_token,
                )

        # ── 5. 合并结果 ────────────────────────────────────────────────────────
        combined: dict[str, dict] = {}
        for img_id, local_path in local_map.items():
            combined[img_id] = {
                "local_path": str(local_path.resolve()),
                "wechat_url": wechat_upload_map.get(img_id, {}).get("wechat_url", ""),
                "media_id": wechat_upload_map.get(img_id, {}).get("media_id", ""),
            }
        job.wechat_image_map = combined

        _finish_step(job, result, data={
            "generate_inline_images": generate_inline_images,
            "cover_path": job.image_path,
            "image_count": len(combined),
            "images": {k: {"local": v["local_path"], "wechat_url": v["wechat_url"]} for k, v in combined.items()},
        })
    except Exception as e:
        _fail_step(job, result, str(e))


# ── Step 6: 替换占位符 + 微信 HTML 清洗 ────────────────────────────────────────

@router.post("/step/convert_html", response_model=ConvertHtmlResponse, summary="Step6: 替换图片占位符 & 转换微信 HTML")
async def step_convert_html(req: ConvertHtmlRequest, background_tasks: BackgroundTasks):
    job = _get_job_or_404(req.job_id)
    if not job.article_body_html:
        raise HTTPException(status_code=400, detail="请先完成 Step4（生成文章）")
    
    failed_step = any(
        s.step == StepName.CONVERT_HTML and s.status == JobStatus.FAILED
        for s in job.steps
    )
    if not failed_step and job.status == JobStatus.FAILED:
        raise HTTPException(status_code=400, detail="当前 Job 有其他步骤失败，请先重试失败的步骤")
    
    if failed_step:
        clear_pause_signal(req.job_id)
        job.status = JobStatus.RUNNING
        job.error = None
        pipeline_store.save(job)
    background_tasks.add_task(_run_convert_html, req.job_id, retry=failed_step)
    return ConvertHtmlResponse(success=True, message="HTML 转换任务已提交" + ("（重试）" if failed_step else ""), job_id=req.job_id)


def _run_convert_html(job_id: str, retry: bool = False):
    from app.services.wechat_service import replace_image_placeholders
    from app.services.html_service import convert_to_wechat_html

    job = _check_job_alive(job_id)
    if not job:
        return
    result = _begin_step(job, StepName.CONVERT_HTML, retry=retry)
    try:
        # 使用 Markdown 转换为 HTML
        html = convert_to_wechat_html(job.article_body_markdown, is_markdown=True)

        # ── 1. 替换占位符（仅文中插图开启时才替换）──────────────────────────
        # generate_inline_images=False 时 article_body_markdown 已无占位符，直接清洗即可
        if job.generate_inline_images and job.wechat_image_map:
            html = replace_image_placeholders(html, job.wechat_image_map)

        # ── 2. 微信白名单 HTML 清洗 ───────────────────────────────────────────
        wechat_html = html  # 已经是微信兼容的 HTML

        # ── 3. 保存到文件 ──────────────────────────────────────────────────────
        output_path = (cfg.outputs_dir / f"{job_id}_wechat.html").resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(wechat_html, encoding="utf-8")

        job.article_html = wechat_html
        job.wechat_html_path = str(output_path)

        _finish_step(job, result, data={
            "wechat_html_path": str(output_path),
            "title": job.article_title,
            "generate_inline_images": job.generate_inline_images,
            "preview": wechat_html[:500],
        })
    except Exception as e:
        _fail_step(job, result, str(e))


# ── Step 7: 发布草稿 ────────────────────────────────────────────────────────

@router.post("/step/publish_draft", response_model=PublishDraftResponse, summary="Step7: 发布微信草稿")
async def step_publish_draft(req: PublishDraftRequest, background_tasks: BackgroundTasks):
    job = _get_job_or_404(req.job_id)
    if not job.article_html and not job.wechat_html_path:
        raise HTTPException(status_code=400, detail="请先完成 Step6（转换 HTML）")
    if not job.image_path:
        raise HTTPException(status_code=400, detail="请先完成 Step5（生成配图），需要封面图")

    appid = req.appid or cfg.wechat_appid
    appsecret = req.appsecret or cfg.wechat_appsecret
    if not appid or not appsecret:
        raise HTTPException(status_code=400, detail="AppID 和 AppSecret 不能为空")
    
    failed_step = any(
        s.step == StepName.PUBLISH_DRAFT and s.status == JobStatus.FAILED
        for s in job.steps
    )
    if not failed_step and job.status == JobStatus.FAILED:
        raise HTTPException(status_code=400, detail="当前 Job 有其他步骤失败，请先重试失败的步骤")

    if failed_step:
        clear_pause_signal(req.job_id)
        job.status = JobStatus.RUNNING
        job.error = None
        pipeline_store.save(job)
    background_tasks.add_task(
        _run_publish_draft, req.job_id, appid, appsecret,
        req.title, req.author, req.digest,
        req.content_source_url, req.original_notice, retry=failed_step,
    )
    return PublishDraftResponse(success=True, message="发布任务已提交" + ("（重试）" if failed_step else ""), job_id=req.job_id)


def _run_publish_draft(job_id, appid, appsecret, title, author, digest, content_source_url, original_notice, retry: bool = False):
    from app.services.wechat_service import publish_draft

    job = _check_job_alive(job_id)
    if not job:
        return
    result = _begin_step(job, StepName.PUBLISH_DRAFT, retry=retry)
    try:
        # 取最终 HTML
        if job.wechat_html_path and Path(job.wechat_html_path).exists():
            content_html = Path(job.wechat_html_path).read_text(encoding="utf-8")
        else:
            content_html = job.article_html

        # 标题优先级：请求参数 > AI 直接输出的标题
        resolved_title = title or job.article_title or None

        publish_result = publish_draft(
            appid=appid,
            appsecret=appsecret,
            content_html=content_html,
            cover_image_path=Path(job.image_path),   # 封面图
            title=resolved_title,
            author=author or None,
            digest=digest or None,
            content_source_url=content_source_url or None,
            original_notice=original_notice or None,
        )

        job.draft_media_id = publish_result["media_id"]
        job.draft_preview_url = publish_result["preview_url"]
        job.status = JobStatus.SUCCESS

        _finish_step(job, result, data={
            "media_id": publish_result["media_id"],
            "preview_url": publish_result["preview_url"],
        })
    except Exception as e:
        _fail_step(job, result, str(e))
