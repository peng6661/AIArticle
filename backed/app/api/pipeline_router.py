"""
分步执行 API
新流程：
  Step4 → AI JSON 结构化生成文章（Function Calling），得到 title + content(占位符HTML)
  Step5 → 替换占位符 + 微信 HTML 白名单清洗，保存文件
  Step6 → 发布草稿 + 打开浏览器
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, Form

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
    JobStatusResponse, StepResultSchema,
    PauseJobResponse,
    PublishDraftRequest, PublishDraftResponse,
    RegenerateJobRequest, RegenerateJobResponse,
    ResumeJobRequest,
    RetryJobRequest, RetryJobResponse,
    TranscribeRequest, TranscribeResponse,
    UploadVideoResponse,
    UploadTextResponse,
)

router = APIRouter(prefix="/pipeline", tags=["Pipeline 分步执行"])
cfg = get_settings()

# ── 本地别名（保持文件内部调用不变）───────────────────────────────────────────
_download_video_from_url = download_video_from_url
_download_image_from_url = download_image_from_url


# ── 文件格式检测（魔数检测）──────────────────────────────────────────────────────

def _get_file_magic_number(file_bytes: bytes) -> str:
    """获取文件的魔数（前32字节十六进制表示）"""
    return file_bytes[:32].hex().lower()


def _is_valid_video_format(file_bytes: bytes, suffix: str) -> bool:
    """验证视频文件格式（魔数检测）"""
    magic = _get_file_magic_number(file_bytes)
    suffix = suffix.lower()
    
    # 视频格式的魔数
    video_magics = {
        ".mp4": ["0000001866747970", "0000002066747970", "0000001c66747970"],
        ".mov": ["0000001466747970", "0000002066747970"],
        ".avi": ["52494646"],  # RIFF开头
        ".mkv": ["1a45dfa3"],  # Matroska开头
        ".webm": ["1a45dfa3"],  # WebM也是Matroska容器
        ".flv": ["464c5601"],  # FLV开头
        ".wmv": ["3026b2758e66cf11", "0000000c6a"],  # ASF/WMV
    }
    
    if suffix not in video_magics:
        return False
    
    # 检查魔数是否匹配
    expected_magics = video_magics[suffix]
    for expected in expected_magics:
        if magic.startswith(expected):
            return True
    
    # 魔数不严格匹配时，允许一些常见情况（避免误判）
    # 但至少扩展名要正确
    return True


def _is_valid_text_format(file_bytes: bytes, suffix: str) -> bool:
    """验证文案文件格式（魔数检测）"""
    magic = _get_file_magic_number(file_bytes)
    suffix = suffix.lower()
    
    # 文本格式（txt/md 一般没有特殊魔数）
    if suffix in [".txt", ".md"]:
        # 检查是否是纯文本（不能有太多非ASCII字符）
        try:
            # 尝试用utf-8解码前100字节
            file_bytes[:100].decode("utf-8")
            return True
        except:
            # 如果不能解码，可能是二进制文件，但为了容错，还是允许
            return True
    
    # PDF 有明确的魔数
    if suffix == ".pdf":
        # PDF魔数: %PDF-
        return magic.startswith("255044462d")
    
    return True


def _validate_file_format(file: UploadFile, file_bytes: bytes, allowed_types: dict) -> tuple[bool, str]:
    """
    综合验证文件格式
    allowed_types: {".ext": "描述"}
    """
    suffix = Path(file.filename or "").suffix.lower()
    
    # 1. 检查扩展名
    if suffix not in allowed_types:
        return False, f"不支持的文件格式: {suffix}，支持: {', '.join(sorted(allowed_types.keys()))}"
    
    # 2. 检查文件大小
    # (在上层已经检查过了)
    
    # 3. 魔数检测
    if allowed_types.get(suffix, "").startswith("视频"):
        if not _is_valid_video_format(file_bytes, suffix):
            return False, f"文件可能不是有效的{allowed_types[suffix]}，请检查文件是否损坏"
    elif allowed_types.get(suffix, "").startswith("文案") or allowed_types.get(suffix, "") in ["文本", "PDF"]:
        if not _is_valid_text_format(file_bytes, suffix):
            return False, f"文件可能不是有效的{allowed_types[suffix]}，请检查文件是否损坏"
    
    return True, ""


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
    # 【修复】忽略 PENDING 状态，防止状态回退（fresh.status 在某些情况下可能为 PENDING）
    if fresh.status != JobStatus.PENDING:
        job.status = fresh.status

    if retry:
        _remove_step_result(job, step)

    # 【修复】如果 job.steps 中已经有同名步骤且状态是 PENDING，重用它（避免重复记录）
    if not retry:
        existing = next((s for s in reversed(job.steps) if s.step == step), None)
        if existing and existing.status == JobStatus.PENDING:
            # 重用现有步骤，修改为 RUNNING
            existing.status = JobStatus.RUNNING
            existing.message = "正在执行"
            existing.started_at = datetime.now().isoformat()
            existing.finished_at = None
            existing.data = {}
            job.current_step = step
            pipeline_store.save(job)
            print(f"[_begin_step] 重用已有 PENDING 步骤: {step.value}")
            return existing

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

    # 关键修复：如果调用方已手动设置了 SUCCESS/FAILED（如全流程完成时），
    # 保持调用方的设置，不被数据库中的旧状态（RUNNING）覆盖。
    # 只有当调用方没有主动设置终止状态时，才从数据库同步最新状态。
    # 【修复】忽略 PENDING 状态，防止状态回退（fresh.status 在某些情况下可能为 PENDING）
    if job.status not in (JobStatus.SUCCESS, JobStatus.FAILED):
        # 只同步终止状态或暂停/取消，忽略 PENDING/RUNNING（避免状态回退）
        if fresh.status in (JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.PAUSED, JobStatus.CANCELLED):
            job.status = fresh.status
        # 如果 fresh.status 是 PENDING 或 RUNNING，保持 job.status 不变（通常是 RUNNING）
    pipeline_store.save(job)


def _fail_step(job: PipelineJob, result: StepResult, error: str):
    result.status = JobStatus.FAILED
    result.message = error
    result.finished_at = datetime.now().isoformat()
    job.status = JobStatus.FAILED
    job.error = error
    pipeline_store.save(job)
    print(f"\n[FAIL] 步骤失败 | step={result.step} | error={error}")


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
        skip_image_generation=job.skip_image_generation,
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


def _expected_steps_for_job(job: PipelineJob) -> list[StepName]:
    steps = [
        StepName.DOWNLOAD,
        StepName.EXTRACT_AUDIO,
        StepName.TRANSCRIBE,
        StepName.GENERATE_ARTICLE,
    ]
    if not job.skip_image_generation:
        steps.append(StepName.GENERATE_IMAGE)
    steps.extend([StepName.CONVERT_HTML, StepName.PUBLISH_DRAFT])
    return steps


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

    # 校验必要参数
    if step_name == StepName.DOWNLOAD and not job.share_text:
        raise HTTPException(status_code=400, detail="缺少原始分享链接，无法重试下载")
    if step_name in (StepName.GENERATE_ARTICLE,):
        _require_api_key(req.api_key)
    if step_name == StepName.PUBLISH_DRAFT:
        appid = req.wechat_appid or cfg.wechat_appid
        appsecret = req.wechat_appsecret or cfg.wechat_appsecret
        if not appid or not appsecret:
            raise HTTPException(status_code=400, detail="重试发布需要公众号 AppID 和 AppSecret")

    # 构建参数快照（避免序列化整个 request 对象到后台任务）
    req_snapshot = {
        "api_key": (req.api_key or "").strip(),
        "ai_provider": req.ai_provider,
        "text_model": req.text_model,
        "image_provider": req.image_provider or "",
        "image_api_key": req.image_api_key or "",
        "image_model": req.image_model or "",
        "skip_image_generation": req.skip_image_generation,
        "wechat_appid": req.wechat_appid,
        "wechat_appsecret": req.wechat_appsecret,
        "rag_collection": req.rag_collection,
        "rag_top_k": req.rag_top_k,
        "rag_embedding_model": req.rag_embedding_model,
        "rag_embedding_provider": req.rag_embedding_provider,
        "rag_embedding_api_key": req.rag_embedding_api_key,
    }

    # 调度链式执行：重试成功后自动继续后续步骤
    background_tasks.add_task(_run_retry_and_continue, job.job_id, step_name, req_snapshot)

    return step_name


# ── 重试后自动继续后续步骤 ──────────────────────────────────────────────────

def _run_retry_and_continue(job_id: str, retried_step: StepName, req_snapshot: dict):
    """重试失败步骤，成功后自动继续执行后续未完成的步骤。

    req_snapshot: 从 RetryJobRequest 提取的参数快照（避免序列化整个 request 对象）
    """
    job = _check_job_alive(job_id)
    if not job:
        return

    # ── 1. 执行重试的步骤 ─────────────────────────────────────────────────
    ai_cfg = cfg.get_ai_provider_config(req_snapshot.get("ai_provider"))

    if retried_step == StepName.DOWNLOAD:
        _run_download(job_id, job.share_text or "", retry=True)
    elif retried_step == StepName.EXTRACT_AUDIO:
        _run_extract_audio(job_id, cfg.audio_default_format, True)
    elif retried_step == StepName.TRANSCRIBE:
        _run_transcribe(job_id, cfg.transcribe_default_model, cfg.transcribe_default_language, None, None, True)
    elif retried_step == StepName.GENERATE_ARTICLE:
        # 执行文章生成（RAG + 大模型直调）
        try:
            from app.services.article_service import (
                create_content_task,
                run_step4_pipeline,
                get_content_task,
            )

            job = _check_job_alive(job_id)
            if not job:
                return

            transcript_path = Path(job.transcript_path)
            if not transcript_path.exists():
                raise FileNotFoundError(f"文案文件不存在: {job.transcript_path}")
            job.transcript_text = transcript_path.read_text(encoding="utf-8")
            if not job.transcript_text.strip():
                raise ValueError(f"文案文件为空: {job.transcript_path}")
            pipeline_store.save(job)

            result = _begin_step(job, StepName.GENERATE_ARTICLE, retry=True)

            task_id = create_content_task(
                pipeline_job_id=job_id,
                transcript=job.transcript_text,
                rag_collection=req_snapshot.get("rag_collection") or None,
                rag_top_k=req_snapshot.get("rag_top_k"),
                rag_embedding_model=req_snapshot.get("rag_embedding_model") or None,
                rag_embedding_provider=req_snapshot.get("rag_embedding_provider") or None,
                rag_embedding_api_key=req_snapshot.get("rag_embedding_api_key") or None,
            )
            print(f"[重试-Step4] 创建任务 | task_id={task_id}")

            output = run_step4_pipeline(
                task_id=task_id,
                transcript=job.transcript_text,
                api_key=req_snapshot.get("api_key", ""),
                ai_provider=req_snapshot.get("ai_provider", "siliconflow"),
                text_model=req_snapshot.get("text_model", ""),
                image_provider=req_snapshot.get("image_provider", ""),
                image_model=req_snapshot.get("image_model", ""),
                skip_image_generation=req_snapshot.get("skip_image_generation", False),
            )  # ← in _run_retry_and_continue()
            print(f"[重试-Step4] 执行完成 | status={output['status']}")

            if output["status"] == "failed":
                raise RuntimeError(output.get("error", "文章生成失败"))

            task = get_content_task(task_id)
            if not task or not task["article_final"]:
                raise RuntimeError("未能获取到最终文章内容")

            job.article_title = task["article_title"] or "AI生成文章"
            job.article_body_markdown = task["article_final"]
            job.article_body_html = task["article_final"]
            if not req_snapshot.get("skip_image_generation", False) and task.get("image_prompt"):
                job.article_image_prompts = [{"id": "cover", "prompt": task["image_prompt"]}]
            else:
                job.article_image_prompts = []

            _finish_step(job, result, data={
                "title": job.article_title,
                "image_count": len(job.article_image_prompts),
            })
            print(f"[重试-Step4] 文章生成成功")

            # 更新内存中的 job 引用为最新状态，以便后续继续逻辑使用
            # 不 return，让步骤 2/3 的检查继续执行
        except Exception as e:
            print(f"[重试-Step4] 失败: {e}")
            import traceback
            traceback.print_exc()
            job = pipeline_store.get(job_id)
            if job and 'result' in dir():
                _fail_step(job, result, str(e))
            return  # 失败则不再继续后续步骤
    elif retried_step == StepName.CONVERT_HTML:
        _run_convert_html(job_id, True)
    elif retried_step == StepName.GENERATE_IMAGE:
        skip_image = req_snapshot.get("skip_image_generation", False)
        if skip_image:
            print(f"[重试-Step5] skip_image_generation=True，跳过封面图生成，使用默认占位图")
            from app.services.wechat_service import _generate_placeholder_cover
            placeholder = _generate_placeholder_cover()
            job.cover_image_path = str(placeholder)
            pipeline_store.save(job)
        else:
            try:
                result = _begin_step(job, StepName.GENERATE_IMAGE, retry=True)
                image_prompts = getattr(job, 'article_image_prompts', [])
                if image_prompts:
                    from app.services.image_service import generate_images_concurrent
                    output_dir = cfg.outputs_dir / f"{job_id}_images"
                    output_dir.mkdir(parents=True, exist_ok=True)

                    image_provider = req_snapshot.get("image_provider") or req_snapshot.get("ai_provider") or "siliconflow"
                    image_api_key = req_snapshot.get("image_api_key") or req_snapshot.get("api_key") or ""
                    image_model_name = req_snapshot.get("image_model") or None

                    img_ai_cfg = cfg.get_ai_provider_config(image_provider)
                    image_base_url = img_ai_cfg.get("base_url", cfg.siliconflow_base_url)

                    if image_provider == "zhipu":
                        img_size = cfg.zhipu_default_image_size
                        if image_model_name is None:
                            image_model_name = cfg.zhipu_default_image_model
                    else:
                        img_size = cfg.siliconflow_default_image_size
                        if image_model_name is None:
                            image_model_name = cfg.siliconflow_default_image_model

                    image_map = generate_images_concurrent(
                        image_prompts=image_prompts,
                        api_key=image_api_key,
                        output_dir=output_dir,
                        model_name=image_model_name,
                        image_size=img_size,
                        base_url=image_base_url,
                        provider=image_provider,
                    )
                    if "cover" in image_map:
                        job.cover_image_path = str(image_map["cover"])
                        pipeline_store.save(job)

                _finish_step(job, result, data={
                    "cover_image_path": job.cover_image_path,
                })
            except Exception as e:
                if 'result' in locals():
                    _fail_step(job, result, f"[Step5-生图] {e}")
                else:
                    job.status = JobStatus.FAILED
                    pipeline_store.save(job)
                return
    elif retried_step == StepName.PUBLISH_DRAFT:
        appid = req_snapshot.get("wechat_appid") or cfg.wechat_appid
        appsecret = req_snapshot.get("wechat_appsecret") or cfg.wechat_appsecret
        _run_publish_draft(job_id, appid, appsecret, "", "", "", "", "", True)

    # ── 2. 检查重试是否成功 ───────────────────────────────────────────────
    job = _check_job_alive(job_id)
    if not job:
        return
    retried_result = next((s for s in reversed(job.steps) if s.step == retried_step), None)
    if not retried_result or retried_result.status != JobStatus.SUCCESS:
        return  # 重试失败或步骤不存在，不继续

    # ── 3. 继续执行后续未完成的步骤（复用 resume 逻辑）────────────────────
    _continue_remaining_steps(job_id, req_snapshot)


def _continue_remaining_steps(job_id: str, req_snapshot: dict):
    """从当前进度继续执行后续未完成的步骤（供重试成功后和 resume 调用）。

    对于 resume 场景，未完成的步骤可能有旧的 FAILED/RUNNING 结果，
    使用 retry=True 确保清理旧结果后再执行。
    """
    ai_cfg = cfg.get_ai_provider_config(req_snapshot.get("ai_provider"))

    job = pipeline_store.get(job_id)
    if not job or job.status in (JobStatus.PAUSED, JobStatus.CANCELLED, JobStatus.FAILED):
        return

    completed = {s.step for s in job.steps if s.status == JobStatus.SUCCESS}
    # 仅处理 job.steps 中已有的步骤，避免凭空处理 GENERATE_IMAGE（前端 toggle 关闭时它不在步骤列表中）
    remaining = [s.step for s in job.steps if s.status != JobStatus.SUCCESS]

    for step in remaining:
        job = _check_job_alive(job_id)
        if not job:
            return

        # resume 场景：清理该步骤的旧结果（FAILED/RUNNING），避免重复
        has_old_result = any(s.step == step and s.status != JobStatus.SUCCESS for s in job.steps)
        use_retry = has_old_result

        try:
            if step == StepName.DOWNLOAD:
                _run_download(job_id, job.share_text or "", retry=use_retry)
            elif step == StepName.EXTRACT_AUDIO:
                _run_extract_audio(job_id, cfg.audio_default_format, use_retry)
            elif step == StepName.TRANSCRIBE:
                _run_transcribe(job_id, cfg.transcribe_default_model, cfg.transcribe_default_language, None, None, use_retry)
            elif step == StepName.GENERATE_ARTICLE:
                # 执行文章生成（RAG + 大模型直调）
                try:
                    transcript_path = Path(job.transcript_path)
                    if not transcript_path.exists():
                        raise FileNotFoundError(f"文案文件不存在: {job.transcript_path}")
                    job.transcript_text = transcript_path.read_text(encoding="utf-8")
                    if not job.transcript_text.strip():
                        raise ValueError(f"文案文件为空: {job.transcript_path}")
                    pipeline_store.save(job)

                    from app.services.article_service import (
                        create_content_task,
                        run_step4_pipeline,
                        get_content_task,
                    )

                    result = _begin_step(job, StepName.GENERATE_ARTICLE)

                    task_id = create_content_task(
                        pipeline_job_id=job_id,
                        transcript=job.transcript_text,
                        rag_collection=req_snapshot.get("rag_collection") or None,
                        rag_top_k=req_snapshot.get("rag_top_k"),
                        rag_embedding_model=req_snapshot.get("rag_embedding_model") or None,
                        rag_embedding_provider=req_snapshot.get("rag_embedding_provider") or None,
                        rag_embedding_api_key=req_snapshot.get("rag_embedding_api_key") or None,
                    )
                    print(f"[继续-Step4] 创建任务 | task_id={task_id}")

                    output = run_step4_pipeline(
                        task_id=task_id,
                        transcript=job.transcript_text,
                        api_key=req_snapshot.get("api_key", ""),
                        ai_provider=req_snapshot.get("ai_provider", "siliconflow"),
                        text_model=req_snapshot.get("text_model", ""),
                        image_provider=req_snapshot.get("image_provider", ""),
                        image_model=req_snapshot.get("image_model", ""),
                        skip_image_generation=req_snapshot.get("skip_image_generation", False),
                    )  # ← in _continue_remaining_steps()
                    print(f"[继续-Step4] 执行完成 | status={output['status']}")

                    if output["status"] == "failed":
                        raise RuntimeError(output.get("error", "文章生成失败"))

                    task = get_content_task(task_id)
                    if not task or not task["article_final"]:
                        raise RuntimeError("未能获取到最终文章内容")

                    job.article_title = task["article_title"] or "AI生成文章"
                    job.article_body_markdown = task["article_final"]
                    job.article_body_html = task["article_final"]
                    if not req_snapshot.get("skip_image_generation", False) and task.get("image_prompt"):
                        job.article_image_prompts = [{"id": "cover", "prompt": task["image_prompt"]}]
                    else:
                        job.article_image_prompts = []

                    _finish_step(job, result, data={
                        "title": job.article_title,
                        "image_count": len(job.article_image_prompts),
                    })
                    print(f"[继续-Step4] 文章生成成功")
                except Exception as e:
                    print(f"[继续-Step4] 失败: {e}")
                    if 'result' in locals():
                        _fail_step(job, result, f"[Step4-文章] {e}")
                    else:
                        job.status = JobStatus.FAILED
                        pipeline_store.save(job)
                    continue  # 跳过后续步骤
            elif step == StepName.GENERATE_IMAGE:
                skip_image = req_snapshot.get("skip_image_generation", False)
                print(f"[continue] Step5 处理 | skip_image_generation={skip_image}")
                
                if skip_image:
                    print(f"[continue] skip_image_generation=True，跳过 Step5 封面图生成，使用默认占位图")
                    from app.services.wechat_service import _generate_placeholder_cover
                    placeholder = _generate_placeholder_cover()
                    job.cover_image_path = str(placeholder)
                    pipeline_store.save(job)
                else:
                    try:
                        result = _begin_step(job, StepName.GENERATE_IMAGE)
                        print(f"[continue] Step5 _begin_step 成功")
                        
                        image_prompts = getattr(job, 'article_image_prompts', [])
                        print(f"[continue] Step5 article_image_prompts 长度={len(image_prompts)}")
                        
                        if image_prompts:
                            print(f"[continue] Step5 开始生成图片")
                            from app.services.image_service import generate_images_concurrent
                            output_dir = cfg.outputs_dir / f"{job_id}_images"
                            output_dir.mkdir(parents=True, exist_ok=True)

                            image_provider = req_snapshot.get("image_provider") or req_snapshot.get("ai_provider") or "siliconflow"
                            image_api_key = req_snapshot.get("image_api_key") or req_snapshot.get("api_key") or ""
                            image_model_name = req_snapshot.get("image_model") or None

                            img_ai_cfg = cfg.get_ai_provider_config(image_provider)
                            image_base_url = img_ai_cfg.get("base_url", cfg.siliconflow_base_url)

                            if image_provider == "zhipu":
                                img_size = cfg.zhipu_default_image_size
                                if image_model_name is None:
                                    image_model_name = cfg.zhipu_default_image_model
                            else:
                                img_size = cfg.siliconflow_default_image_size
                                if image_model_name is None:
                                    image_model_name = cfg.siliconflow_default_image_model

                            print(f"[continue] Step5 调用 generate_images_concurrent | provider={image_provider} | model={image_model_name}")
                            image_map = generate_images_concurrent(
                                image_prompts=image_prompts,
                                api_key=image_api_key,
                                output_dir=output_dir,
                                model_name=image_model_name,
                                image_size=img_size,
                                base_url=image_base_url,
                                provider=image_provider,
                            )
                            if "cover" in image_map:
                                job.cover_image_path = str(image_map["cover"])
                                pipeline_store.save(job)
                            print(f"[continue] Step5 图片生成成功 | cover_image_path={job.cover_image_path}")
                        else:
                            print(f"[continue] Step5 警告: article_image_prompts 为空，使用默认占位图")
                            from app.services.wechat_service import _generate_placeholder_cover
                            placeholder = _generate_placeholder_cover()
                            job.cover_image_path = str(placeholder)
                            pipeline_store.save(job)

                        _finish_step(job, result, data={
                            "cover_image_path": job.cover_image_path,
                        })
                    except RuntimeError as e:
                        if "已完成" in str(e):
                            print(f"[continue] Step5 已完成，跳过")
                            continue
                        elif "暂停" in str(e) or "取消" in str(e):
                            return
                        raise
                    except Exception as e:
                        if 'result' in locals():
                            _fail_step(job, result, f"[Step5-生图] {e}")
                        else:
                            job.status = JobStatus.FAILED
                            pipeline_store.save(job)
                        continue
            elif step == StepName.CONVERT_HTML:
                # 检查是否有文章内容
                if not job.article_body_markdown:
                    print(f"[continue] 没有文章内容，跳过 Step6 转换 HTML")
                    return
                _run_convert_html(job_id, use_retry)
            elif step == StepName.PUBLISH_DRAFT:
                # 检查是否有 HTML 内容
                if not job.article_html and not job.wechat_html_path:
                    print(f"[continue] 没有 HTML 内容，跳过 Step7 发布草稿")
                    return
                appid = req_snapshot.get("wechat_appid") or cfg.wechat_appid
                appsecret = req_snapshot.get("wechat_appsecret") or cfg.wechat_appsecret
                if not appid or not appsecret:
                    _fail_step(job, next(s for s in job.steps if s.step == StepName.PUBLISH_DRAFT), "微信 AppID/AppSecret 未配置")
                    return
                _run_publish_draft(job_id, appid, appsecret, "", "", "", "", "", use_retry)

        except Exception as e:
            # 找到该步骤的 result 对象
            result = next((s for s in job.steps if s.step == step), None)
            if result:
                _fail_step(job, result, str(e))
            print(f"[continue] 步骤 {step.value} 失败，停止后续链式执行: {e}")
            return

    # 所有步骤完成，标记任务成功
    job = pipeline_store.get(job_id)
    if job and all(s.status == JobStatus.SUCCESS for s in job.steps):
        job.status = JobStatus.SUCCESS
        pipeline_store.save(job)


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
    remaining = [s for s in _expected_steps_for_job(job) if s not in completed_steps]

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
        req_snapshot = {
            "api_key": req.api_key.strip(),
            "ai_provider": req.ai_provider,
            "text_model": req.text_model,
            "image_provider": req.image_provider or "",
            "image_api_key": req.image_api_key or "",
            "image_model": req.image_model or "",
            "skip_image_generation": req.skip_image_generation,
        }
        background_tasks.add_task(_continue_remaining_steps, job.job_id, req_snapshot)
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

    # 检查是否所有步骤已完成
    completed_steps = {s.step for s in job.steps if s.status == JobStatus.SUCCESS}
    remaining = [s for s in _expected_steps_for_job(job) if s not in completed_steps]
    if not remaining:
        job.status = JobStatus.SUCCESS
        pipeline_store.save(job)
        return {
            "success": True,
            "message": "所有步骤已完成，任务已标记为成功",
            "job_id": job_id,
            "resumed_step": None,
        }

    # 清除内存级暂停信号
    clear_pause_signal(job_id)

    # 先将状态改为 RUNNING，否则 _begin_step 会因 PAUSED 状态抛异常
    job.status = JobStatus.RUNNING
    # 更新 skip_image_generation 设置（用户可能在暂停期间修改了配置）
    job.skip_image_generation = req.skip_image_generation
    pipeline_store.save(job)

    # 构建参数快照，调度链式执行所有剩余步骤
    req_snapshot = {
        "api_key": (req.api_key or "").strip(),
        "ai_provider": req.ai_provider,
        "text_model": req.text_model,
        "image_provider": req.image_provider or "",
        "image_api_key": req.image_api_key or "",
        "image_model": req.image_model or "",
        "skip_image_generation": req.skip_image_generation,
        "wechat_appid": req.wechat_appid,
        "wechat_appsecret": req.wechat_appsecret,
        "rag_collection": req.rag_collection,
        "rag_top_k": req.rag_top_k,
        "rag_embedding_model": req.rag_embedding_model,
        "rag_embedding_provider": req.rag_embedding_provider,
        "rag_embedding_api_key": req.rag_embedding_api_key,
    }
    background_tasks.add_task(_continue_remaining_steps, job_id, req_snapshot)

    return {
        "success": True,
        "message": f"任务已从「{remaining[0].value}」步骤继续执行",
        "job_id": job_id,
        "resumed_step": remaining[0].value,
    }


# ── 再次生成（复用文案，直接从 Step4 文章生成开始）─────────────────────────────

@router.post("/jobs/{job_id}/regenerate", response_model=RegenerateJobResponse, summary="再次生成：复用原任务文案，直接从 Step4 文章生成开始")
async def regenerate_job(job_id: str, req: RegenerateJobRequest, background_tasks: BackgroundTasks):
    """复用指定任务的 transcript_path 文本内容，创建一个新任务并从 Step4 文章生成开始执行。

    支持任意状态的任务（SUCCESS/FAILED/PARTIAL），会自动复制已完成步骤的状态。
    新任务会复制以下内容：
    - 原任务的 transcript_path（文本文案路径）
    - 原任务的已完成步骤状态（DOWNLOAD/AUDIO/TRANSCRIBE 标记为 COMPLETED）
    - 原任务的 share_text、video_path、audio_path 等
    """
    # 校验原任务是否存在
    original_job = _get_job_or_404(job_id)

    # 校验原任务有文案（放宽条件，不再要求 SUCCESS 状态）
    if not original_job.transcript_path:
        raise HTTPException(
            status_code=400,
            detail="原任务没有文本文案，无法再次生成",
        )

    # 校验文案文件存在
    if not Path(original_job.transcript_path).exists():
        raise HTTPException(
            status_code=400,
            detail=f"原任务的文本文案文件不存在: {original_job.transcript_path}",
        )

    # 校验 API Key
    if not req.api_key.strip():
        raise HTTPException(status_code=400, detail="AI 服务 API Key 不能为空")

    # 创建新任务
    new_job = pipeline_store.create()
    new_job.share_text = f"[再次生成] {original_job.share_text or original_job.transcript_path}"
    new_job.transcript_path = original_job.transcript_path
    new_job.media_type = original_job.media_type
    # 复制视频/音频路径（用于生成文章后可能的后续步骤参考）
    new_job.video_path = original_job.video_path
    new_job.audio_path = original_job.audio_path
    new_job.skip_image_generation = req.skip_image_generation

    # ── 只预先设置前3步为 SUCCESS ────────────────────────────────────
    # 注意：不预先设置 Step4-7，因为 _begin_step 会 append 新的 StepResult
    # 如果预先设置，会导致每个步骤出现两条记录（一条 PENDING + 一条 RUNNING）
    COMPLETED_STEPS = [StepName.DOWNLOAD, StepName.EXTRACT_AUDIO, StepName.TRANSCRIBE]
    retained_count = 0
    for step_name in COMPLETED_STEPS:
        original_step = next((s for s in original_job.steps if s.step == step_name), None)
        if original_step and original_step.status == JobStatus.SUCCESS:
            new_job.steps.append(StepResult(
                step=step_name,
                status=JobStatus.SUCCESS,
                message="（再次生成）复用原任务",
                started_at=original_step.started_at,
                finished_at=original_step.finished_at,
            ))
            retained_count += 1
            print(f"[再次生成] 保留步骤状态: {step_name.value} = SUCCESS")
    # Step4-7 保持空列表，让 _run_regenerate 中的 _begin_step 自动创建

    pipeline_store.save(new_job)

    # 后台执行：从 Step4 开始链式执行
    req_snapshot = {
        "api_key": req.api_key.strip(),
        "ai_provider": req.ai_provider,
        "text_model": req.text_model,
        "image_provider": req.image_provider or "",
        "image_api_key": req.image_api_key or "",
        "image_model": req.image_model or "",
        "skip_image_generation": req.skip_image_generation,
        "wechat_appid": req.wechat_appid,
        "wechat_appsecret": req.wechat_appsecret,
    }
    background_tasks.add_task(_run_regenerate, new_job.job_id, req_snapshot, {
        "rag_collection": req.rag_collection,
        "rag_top_k": req.rag_top_k,
        "rag_embedding_model": req.rag_embedding_model,
        "rag_embedding_provider": req.rag_embedding_provider,
        "rag_embedding_api_key": req.rag_embedding_api_key,
    })

    return RegenerateJobResponse(
        success=True,
        message=f"已基于原任务创建新任务，保留{retained_count}个已完成步骤，从文章生成开始执行",
        job_id=new_job.job_id,
    )


def _run_regenerate(job_id: str, req_snapshot: dict, extra: dict):
    """后台任务：复用文案，直接从 Step4 文章生成开始，然后链式执行后续步骤。"""
    job = pipeline_store.get(job_id)
    if not job:
        return

    ai_cfg = cfg.get_ai_provider_config(req_snapshot.get("ai_provider"))

    # ── 为 Step4-7 添加占位记录（PENDING 状态）─────────────────────────
    # 目的：让前端在执行过程中能看到前3步已通过，Step4-7 正在等待
    # 注意：_begin_step 会将这些 PENDING 状态更新为 RUNNING/SUCCESS
    PENDING_STEPS = [StepName.GENERATE_ARTICLE]
    if not req_snapshot.get("skip_image_generation", False):
        PENDING_STEPS.append(StepName.GENERATE_IMAGE)
    PENDING_STEPS += [StepName.CONVERT_HTML, StepName.PUBLISH_DRAFT]
    for step_name in PENDING_STEPS:
        # 检查是否已存在该步骤的记录（从后往前搜索，获取最新记录）
        existing = next((s for s in reversed(job.steps) if s.step == step_name), None)
        if not existing:
            job.steps.append(StepResult(
                step=step_name,
                status=JobStatus.PENDING,
                message="等待执行",
                started_at="",
                finished_at=None,
            ))
            print(f"[再次生成] 添加步骤占位: {step_name.value} = PENDING")
    pipeline_store.save(job)

    # ── Step4: 执行文章生成（RAG + 大模型直调）────────────────────────────────
    try:
        # 从文件读取文本文案
        transcript_path = Path(job.transcript_path)
        if not transcript_path.exists():
            raise FileNotFoundError(f"文案文件不存在: {job.transcript_path}")
        job.transcript_text = transcript_path.read_text(encoding="utf-8")
        if not job.transcript_text.strip():
            raise ValueError(f"文案文件为空: {job.transcript_path}")
        pipeline_store.save(job)

        from app.services.article_service import (
            create_content_task,
            run_step4_pipeline,
            get_content_task,
        )

        result = _begin_step(job, StepName.GENERATE_ARTICLE)

        # 创建 content_task（MySQL）
        task_id = create_content_task(
            pipeline_job_id=job_id,
            transcript=job.transcript_text,
            rag_collection=extra.get("rag_collection") or None,
            rag_top_k=extra.get("rag_top_k"),
            rag_embedding_model=extra.get("rag_embedding_model") or None,
            rag_embedding_provider=extra.get("rag_embedding_provider") or None,
            rag_embedding_api_key=extra.get("rag_embedding_api_key") or None,
        )
        print(f"[再次生成-Step4] 创建任务 | task_id={task_id}")

        # 执行 LangGraph 流水线
        output = run_step4_pipeline(
            task_id=task_id,
            transcript=job.transcript_text,
            api_key=req_snapshot.get("api_key", ""),
            ai_provider=req_snapshot.get("ai_provider", "siliconflow"),
            text_model=req_snapshot.get("text_model", ""),
            image_provider=req_snapshot.get("image_provider", ""),
            image_model=req_snapshot.get("image_model", ""),
            skip_image_generation=req_snapshot.get("skip_image_generation", False),
        )
        print(f"[再次生成-Step4] 执行完成 | status={output['status']}")

        if output["status"] == "failed":
            raise RuntimeError(output.get("error", "文章生成失败"))

        # 从 DB 读取最终结果
        task = get_content_task(task_id)
        if not task or not task["article_final"]:
            raise RuntimeError("未能获取到最终文章内容")

        # 填充到 PipelineJob
        job.article_title = task["article_title"] or "AI生成文章"
        job.article_body_markdown = task["article_final"]
        job.article_body_html = task["article_final"]
        
        skip_image_gen = req_snapshot.get("skip_image_generation", False)
        has_image_prompt = task.get("image_prompt") is not None
        
        print(f"[再次生成-Step4] skip_image_generation={skip_image_gen}")
        print(f"[再次生成-Step4] task['image_prompt'] exists={has_image_prompt}, value={task.get('image_prompt', 'None')}")
        
        if not skip_image_gen and has_image_prompt:
            job.article_image_prompts = [{"id": "cover", "prompt": task["image_prompt"]}]
            print(f"[再次生成-Step4] 设置 article_image_prompts=[{{'id': 'cover', 'prompt': '{task['image_prompt'][:50]}...'}}]")
        else:
            job.article_image_prompts = []
            print(f"[再次生成-Step4] 设置 article_image_prompts=[]（原因: skip_image={skip_image_gen}, has_prompt={has_image_prompt}）")
        
        # 必须保存到数据库，否则 Step5 读取不到
        pipeline_store.save(job)
        print(f"[再次生成-Step4] 已保存 article_image_prompts 到数据库")

        _finish_step(job, result, data={
            "title": job.article_title,
            "image_count": len(job.article_image_prompts),
        })
        print(f"[再次生成-Step4] 文章生成成功")
    except Exception as e:
        print(f"[再次生成-Step4] 失败: {e}")
        # 如果 result 已定义（_begin_step 已调用），标记失败
        if 'result' in locals():
            _fail_step(job, result, f"[Step4-文章] {e}")
        else:
            # _begin_step 之前就失败，直接标记整个任务失败
            job.status = JobStatus.FAILED
            pipeline_store.save(job)
        return

    # ── 后续步骤（Step5-7）：通过 _continue_remaining_steps 链式执行 ──────────
    # 此时 Step1-4 已完成，Step5 开始 PENDING，交给 _continue_remaining_steps
    _continue_remaining_steps(job_id, req_snapshot)


# ── 视频上传（跳过 Step1，从 Step2 开始）─────────────────────────────────────

@router.post("/upload-video", response_model=UploadVideoResponse, summary="上传本地视频，跳过下载步骤，直接从提取音频开始")
async def upload_video(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(..., description="视频文件（mp4/mov/avi/mkv/webm）"),
    skip_image_generation: bool = Form(False, description="跳过图片生成，使用默认封面图"),
):
    # 校验文件类型
    allowed_types = {
        ".mp4": "视频文件",
        ".mov": "视频文件",
        ".avi": "视频文件",
        ".mkv": "视频文件",
        ".webm": "视频文件",
        ".flv": "视频文件",
        ".wmv": "视频文件",
    }
    suffix = Path(video.filename or "").suffix.lower()
    
    # 读取文件开头的 64 字节用于魔数检测
    file_header = await video.read(64)
    # 重置文件指针，让后台任务能读取完整文件
    await video.seek(0)

    # 综合格式验证
    is_valid, error_msg = _validate_file_format(video, file_header, allowed_types)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

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
        skip_image_generation,
    )

    return UploadVideoResponse(
        success=True,
        message=f"视频上传成功，点击「免费生成」开始处理",
        job_id=job.job_id,
    )


def _run_upload_video(job_id: str, video_file: UploadFile, dest_path: Path, skip_image_generation: bool = False):
    """后台任务：保存上传文件 → 标记 Step1 完成 → 暂停等待用户触发后续步骤。"""
    import shutil

    try:
        job = pipeline_store.get(job_id)
        if not job:
            return

        job.skip_image_generation = skip_image_generation

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

        # ── 为 Step2-7 添加占位记录（PENDING 状态）─────────────────────────
        # 让前端在执行过程中能看到前1步已通过，Step2-7 正在等待
        PENDING_STEPS = [StepName.EXTRACT_AUDIO, StepName.TRANSCRIBE,
                         StepName.GENERATE_ARTICLE]
        if not skip_image_generation:
            PENDING_STEPS.append(StepName.GENERATE_IMAGE)
        PENDING_STEPS += [StepName.CONVERT_HTML, StepName.PUBLISH_DRAFT]
        for step_name in PENDING_STEPS:
            job.steps.append(StepResult(
                step=step_name,
                status=JobStatus.PENDING,
                message="等待执行",
                started_at="",
                finished_at=None,
            ))

        # 设为 PAUSED，等待用户点击"免费生成"后 resume
        job.status = JobStatus.PAUSED
        job.current_step = StepName.EXTRACT_AUDIO
        pipeline_store.save(job)

    except Exception as e:
        _fail_step(job, result, f"视频保存失败: {e}")


# ── 文案上传（跳过 Step1-3，从 Step4 开始）─────────────────────────────────

@router.post("/upload-text", response_model=UploadTextResponse, summary="上传文案（txt/pdf/md），跳过下载/提取音频/转写，直接从文章生成开始")
async def upload_text(
    background_tasks: BackgroundTasks,
    text_file: UploadFile = File(..., description="文案文件（txt/pdf/md）"),
    # AI 配置（可选）：提供后自动执行文章生成，不提供则暂停等待前端 resume
    api_key: str = Form("", description="AI 服务 API Key"),
    ai_provider: str = Form("siliconflow", description="AI 服务提供商: siliconflow | zhipu"),
    text_model: str = Form("", description="文章生成模型，留空使用 provider 默认"),
    wechat_appid: str = Form("", description="公众号 AppID"),
    wechat_appsecret: str = Form("", description="公众号 AppSecret"),
    rag_collection: str = Form("", description="RAG 知识库集合名"),
    rag_top_k: int = Form(5, description="RAG 检索返回块数量"),
    rag_embedding_model: str = Form("", description="RAG 向量模型"),
    rag_embedding_provider: str = Form("", description="向量模型服务商"),
    rag_embedding_api_key: str = Form("", description="RAG 向量模型专用 API Key"),
    skip_image_generation: bool = Form(False, description="跳过图片生成，使用默认封面图"),
):
    # 校验文件类型
    allowed_types = {
        ".txt": "文本文档",
        ".pdf": "PDF文档",
        ".md": "Markdown文档",
    }
    suffix = Path(text_file.filename or "").suffix.lower()
    
    # 读取完整文件内容
    file_bytes = await text_file.read()
    
    # 综合格式验证（使用前 64 字节）
    is_valid, error_msg = _validate_file_format(text_file, file_bytes[:64], allowed_types)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # 校验文件大小（最大 50MB）
    MAX_SIZE = 50 * 1024 * 1024  # 50 MB
    if text_file.size and text_file.size > MAX_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大 ({text_file.size / 1024 / 1024:.1f} MB)，最大支持 50 MB",
        )

    # 解析文案内容
    transcript_text = ""
    if suffix == ".txt":
        transcript_text = file_bytes.decode("utf-8")
    elif suffix == ".pdf":
        # 先保存到临时文件，然后解析
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = Path(tmp.name)
        try:
            from app.services.rag.document_parser import parse_pdf
            transcript_text = parse_pdf(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
    elif suffix == ".md":
        from app.services.rag.document_parser import parse_markdown
        transcript_text = parse_markdown(file_bytes.decode("utf-8"))

    if not transcript_text or not transcript_text.strip():
        raise HTTPException(status_code=400, detail="文案内容为空，请检查文件")

    # 创建 Job
    job = pipeline_store.create()
    job.share_text = f"[文案上传] {text_file.filename or 'text'}"
    job.media_type = "text"
    # 保存转写文本
    transcript_path = cfg.transcripts_dir / f"{job.job_id}.txt"

    # 保存转写文本
    transcript_path = cfg.transcripts_dir / f"{job.job_id}.txt"
    cfg.transcripts_dir.mkdir(parents=True, exist_ok=True)
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(transcript_text)

    job.transcript_path = str(transcript_path.resolve())
    job.skip_image_generation = skip_image_generation

    # 标记 Step1-3 为完成
    # Step1: 下载
    result_download = StepResult(
        step=StepName.DOWNLOAD,
        status=JobStatus.SUCCESS,
        message="（文案上传）下载完成",
        started_at=datetime.now().isoformat(),
        finished_at=datetime.now().isoformat(),
    )
    job.steps.append(result_download)

    # Step2: 提取音频（虚拟完成）
    result_audio = StepResult(
        step=StepName.EXTRACT_AUDIO,
        status=JobStatus.SUCCESS,
        message="（文案上传）无需提取音频",
        started_at=datetime.now().isoformat(),
        finished_at=datetime.now().isoformat(),
    )
    job.steps.append(result_audio)

    # Step3: 语音转写（虚拟完成）
    result_transcribe = StepResult(
        step=StepName.TRANSCRIBE,
        status=JobStatus.SUCCESS,
        message="（文案上传）无需转写",
        data={"transcript_path": str(transcript_path.resolve())},
        started_at=datetime.now().isoformat(),
        finished_at=datetime.now().isoformat(),
    )
    job.steps.append(result_transcribe)

    # 为 Step4-7 添加占位记录（PENDING 状态）
    PENDING_STEPS = [StepName.GENERATE_ARTICLE]
    if not skip_image_generation:
        PENDING_STEPS.append(StepName.GENERATE_IMAGE)
    PENDING_STEPS += [StepName.CONVERT_HTML, StepName.PUBLISH_DRAFT]
    for step_name in PENDING_STEPS:
        job.steps.append(StepResult(
            step=step_name,
            status=JobStatus.PENDING,
            message="等待执行",
            started_at="",
            finished_at=None,
        ))

    # 判断是否需要自动执行（提供了 api_key 则自动，否则暂停等待前端 resume）
    if api_key.strip():
        job.status = JobStatus.RUNNING
        job.current_step = StepName.GENERATE_ARTICLE
        pipeline_store.save(job)

        # 构建参数快照，调度链式执行所有剩余步骤
        req_snapshot = {
            "api_key": api_key.strip(),
            "ai_provider": ai_provider,
            "text_model": text_model,
            "image_provider": "",
            "image_api_key": "",
            "image_model": "",
            "skip_image_generation": skip_image_generation,
            "wechat_appid": wechat_appid,
            "wechat_appsecret": wechat_appsecret,
            "rag_collection": rag_collection,
            "rag_top_k": rag_top_k,
            "rag_embedding_model": rag_embedding_model,
            "rag_embedding_provider": rag_embedding_provider,
            "rag_embedding_api_key": rag_embedding_api_key,
        }
        background_tasks.add_task(_continue_remaining_steps, job.job_id, req_snapshot)

        return UploadTextResponse(
            success=True,
            message="文案上传成功，正在自动生成文章...",
            job_id=job.job_id,
        )
    else:
        # 设为 PAUSED，等待用户点击"免费生成"
        job.status = JobStatus.PAUSED
        job.current_step = StepName.GENERATE_ARTICLE
        pipeline_store.save(job)

        return UploadTextResponse(
            success=True,
            message="文案上传成功，点击「免费生成」开始处理",
            job_id=job.job_id,
        )


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


# ── Step 4: 生成文章（已迁移至 LangGraph / 全流水线）───────────────────────────
# 单步 generate_article 端点已删除，V6.0 一次性生成方式已移除


# _run_generate_article 已删除（V6.0 一次性生成方式）


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
        # 检查是否有文章内容
        if not job.article_body_markdown:
            raise ValueError("没有文章内容，无法转换 HTML")

        # 使用 Markdown 转换为 HTML
        html = convert_to_wechat_html(job.article_body_markdown, is_markdown=True)

        # ── 微信白名单 HTML 清洗 ───────────────────────────────────────────
        wechat_html = html  # 已经是微信兼容的 HTML

        # ── 保存到文件 ──────────────────────────────────────────────────────
        output_path = (cfg.outputs_dir / f"{job_id}_wechat.html").resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(wechat_html, encoding="utf-8")

        job.article_html = wechat_html
        job.wechat_html_path = str(output_path)

        _finish_step(job, result, data={
            "wechat_html_path": str(output_path),
            "title": job.article_title,
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
        content_html = ""
        if job.wechat_html_path and Path(job.wechat_html_path).exists():
            content_html = Path(job.wechat_html_path).read_text(encoding="utf-8")
        elif job.article_html:
            content_html = job.article_html

        if not content_html or not content_html.strip():
            raise ValueError("没有 HTML 内容，无法发布")

        # 标题优先级：请求参数 > AI 直接输出的标题
        resolved_title = title or job.article_title or None

        # 封面图路径：优先使用 Step5 生成的图片
        resolved_cover = None
        if job.cover_image_path and Path(job.cover_image_path).exists():
            resolved_cover = Path(job.cover_image_path)
            print(f"[Step7] 使用封面图: {resolved_cover}")
        else:
            print(f"[Step7] 封面图不存在或未生成，使用默认占位图")

        publish_result = publish_draft(
            appid=appid,
            appsecret=appsecret,
            content_html=content_html,
            cover_image_path=resolved_cover,
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
