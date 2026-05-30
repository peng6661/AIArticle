"""
一键全流程 API
新流程：
  Step1 下载（抖音/Instagram/B站/TikTok/快手/X/YouTube）→ Step2 提取音频 → Step3 语音转写
  → Step4 AI JSON 文章（Function Calling）
  → Step5 并发生图 + 上传微信素材
  → Step6 替换占位符 + 微信 HTML 清洗
  → Step7 上传封面 + 发布草稿 + 打开浏览器
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks

from app.core.config import get_settings
from app.core.pipeline import JobStatus, StepName, pipeline_store, is_paused
from app.schemas.pipeline import FullPipelineRequest, FullPipelineResponse
from app.api.pipeline_router import _begin_step, _fail_step, _finish_step
from app.api._pipeline_utils import (
    detect_platform, download_video_from_url, download_image_from_url,
    SUPPORTED_PLATFORMS,
)

# 本地别名，与原代码调用名保持一致
_download_video_from_url = download_video_from_url
_download_image_from_url = download_image_from_url

router = APIRouter(prefix="/pipeline", tags=["Pipeline 一键全流程"])
cfg = get_settings()


@router.post("/run", response_model=FullPipelineResponse, summary="一键执行全流程")
async def run_full_pipeline(req: FullPipelineRequest, background_tasks: BackgroundTasks):
    """
    提交全流程任务，立即返回 job_id，通过 GET /pipeline/jobs/{job_id} 查询进度。
    抖音下载 → 提取音频 → 语音转写 → AI生成文章(JSON)
    → 替换占位符+清洗HTML → 发布草稿+打开浏览器
    """
    job = pipeline_store.create()
    job.share_text = req.share_text
    job.skip_image_generation = req.skip_image_generation
    pipeline_store.save(job)
    background_tasks.add_task(_run_full_pipeline_bg, job.job_id, req)
    return FullPipelineResponse(
        success=True,
        message="全流程任务已提交，请通过 job_id 查询进度",
        job_id=job.job_id,
    )


def _run_full_pipeline_bg(job_id: str, req: FullPipelineRequest):
    """后台执行全流程。在每个步骤间检查暂停/取消/删除状态，优雅退出。"""

    def _is_cancelled(jid: str) -> bool:
        """检查任务是否已被暂停、取消或删除（不再可执行）。
        优先使用内存级信号检测（即时），再回退到 DB 检测。
        """
        # 内存级即时检测
        if is_paused(jid):
            return True
        fresh = pipeline_store.get(jid)
        return fresh is None or fresh.status in (JobStatus.PAUSED, JobStatus.CANCELLED)

    # 函数入口处先检查一次
    if _is_cancelled(job_id):
        return

    from app.services.douyin_download_service import DouyinExtractor
    from app.services.instagram_download_service import InstagramExtractor
    from app.services.bilibili_download_service import BilibiliExtractor
    from app.services.tiktok_download_service import TikTokExtractor
    from app.services.kuaishou_download_service import KuaishouExtractor
    from app.services.x_download_service import XVideoExtractor
    from app.services.youtube_download_service import YouTubeExtractor
    from app.services.audio_service import extract_audio
    from app.services.transcribe_service import transcribe_audio
    from app.services.article_service import (
        create_content_task,
        run_step4_pipeline,
        get_content_task,
    )
    from app.services.html_service import convert_to_wechat_html
    from app.services.image_service import generate_images_concurrent
    from app.services.wechat_service import (
        publish_draft
    )

    job = pipeline_store.get(job_id)

    # ── Step 1: 下载视频（支持全平台）──────────────────────────────────────
    try:
        result = _begin_step(job, StepName.DOWNLOAD)
    except RuntimeError as e:
        if "暂停" in str(e) or "取消" in str(e) or "删除" in str(e):
            return
        raise
    try:
        platform = detect_platform(req.share_text)

        if platform == "douyin":
            extractor = DouyinExtractor()
            video_data = extractor.extract(req.share_text)
            if not video_data or video_data.get("error"):
                raise ValueError("无法从分享文本中提取视频链接，请检查输入")
            # 新版 extract() 返回统一格式，用通用下载函数
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
            _finish_step(job, result, data={"video_path": str(video_path), "platform": "douyin"})

        elif platform == "instagram":
            extractor = InstagramExtractor()
            media_data = extractor.extract(req.share_text)
            if not media_data or media_data.get("error"):
                raise ValueError("无法解析 Instagram 链接，请检查输入或确认内容可访问")

            title = media_data.get("title") or "Instagram media"
            images = media_data.get("images", [])
            video_url = media_data.get("video_url") or media_data.get("url", "")

            if images and len(images) > 0:
                # 图片/轮播帖子：逐张下载
                downloaded_paths = []
                for idx, img in enumerate(images):
                    # 内存级暂停检测（循环内部即时响应）
                    if is_paused(job_id):
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
                job.media_type = "image"
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
                job.media_type = "video"
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
            media_data = extractor.extract(req.share_text)
            if not media_data:
                raise ValueError(f"无法解析 {platform_name} 链接，请检查链接是否有效")

            title = media_data.get("title") or f"{platform_name}_video"

            # ── YouTube 特殊处理：CDN 直链有时效性，必须用 yt-dlp 直接下载 ──
            if platform == "youtube":
                media_data["_original_url"] = req.share_text
                downloaded = extractor.download(media_data, save_dir=cfg.downloads_dir)
                if not downloaded:
                    raise ValueError("YouTube 视频下载失败，请检查链接是否有效或稍后重试")
                job.video_path = str(downloaded)
                job.media_type = "video"
                _finish_step(job, result, data={
                    "video_path": str(downloaded),
                    "title": title,
                    "platform": platform,
                    "media_type": "video",
                })
            else:
                # 其他平台：extract() → 直链 → requests 下载
                video_url = media_data.get("video_url", "")
                if not video_url:
                    raise ValueError(f"{platform_name} 未获取到有效的视频下载地址")

                video_path = _download_video_from_url(
                    video_url=video_url,
                    save_dir=cfg.downloads_dir,
                    filename=title,
                    platform=platform,
                )
                job.video_path = str(video_path)
                job.media_type = "video"
                _finish_step(job, result, data={
                    "video_path": str(video_path),
                    "title": title,
                    "platform": platform,
                    "media_type": "video",
                })

        else:
            raise ValueError(f"无法识别的链接平台，支持：{SUPPORTED_PLATFORMS}")

    except Exception as e:
        if isinstance(e, RuntimeError) and ("暂停" in str(e) or "取消" in str(e) or "删除" in str(e)):
            return
        _fail_step(job, result, f"[Step1-下载] {e}")
        return

    # ── Step 2: 提取音频 ──────────────────────────────────────────────────
    try:
        result = _begin_step(job, StepName.EXTRACT_AUDIO)
    except RuntimeError as e:
        if "暂停" in str(e) or "取消" in str(e) or "删除" in str(e):
            return  # 优雅退出，不再执行后续步骤
        raise
    try:
        audio_path = extract_audio(Path(job.video_path), audio_format=req.audio_format)
        job.audio_path = str(audio_path)
        _finish_step(job, result, data={"audio_path": str(audio_path)})
    except Exception as e:
        if isinstance(e, RuntimeError) and ("暂停" in str(e) or "取消" in str(e) or "删除" in str(e)):
            return
        _fail_step(job, result, f"[Step2-音频] {e}")
        return

    # ── Step 3: 语音转写 ──────────────────────────────────────────────────
    try:
        result = _begin_step(job, StepName.TRANSCRIBE)
    except RuntimeError as e:
        if "暂停" in str(e) or "取消" in str(e) or "删除" in str(e):
            return
        raise
    try:
        audio_path = Path(job.audio_path)
        transcript_path = audio_path.with_suffix(".txt")
        text = transcribe_audio(
            audio_path=audio_path, output_path=transcript_path,
            model_size=req.transcribe_model, language=req.language,
            device=req.transcribe_device or None,
            compute_type=req.transcribe_compute_type or None,
        )
        job.transcript_path = str(transcript_path)
        job.transcript_text = text
        _finish_step(job, result, data={"transcript_path": str(transcript_path)})
    except Exception as e:
        if isinstance(e, RuntimeError) and ("暂停" in str(e) or "取消" in str(e) or "删除" in str(e)):
            return
        _fail_step(job, result, f"[Step3-转写] {e}")
        return

    # ── Step 4: AI 生成文章（LangGraph + RAG + MySQL 任务追踪）─────────────
    try:
        result = _begin_step(job, StepName.GENERATE_ARTICLE)
    except RuntimeError as e:
        if "暂停" in str(e) or "取消" in str(e) or "删除" in str(e):
            return
        raise
    try:
        # ── 打印配置信息，方便调试 ──────────────────────────────────────
        masked_key = (req.siliconflow_api_key[:6] + "****" + req.siliconflow_api_key[-4:]) if req.siliconflow_api_key and len(req.siliconflow_api_key) > 10 else "（空）"
        _text_model = req.text_model or cfg.siliconflow_default_text_model
        print(f"\n{'='*60}")
        print(f"[Step4-文章] 配置信息 | job_id={job_id}")
        print(f"  model     = {_text_model}")
        print(f"  rag       = {req.rag_collection or '(未配置)'}")
        print(f"  skip_image_generation = {req.skip_image_generation}")
        print(f"  image_provider = {req.image_provider or '(未配置)'}")
        print(f"  image_model = {req.image_model or '(未配置)'}")
        print(f"{'='*60}\n")

        # 1. 在 MySQL 中创建 content_task
        task_id = create_content_task(
            pipeline_job_id=job_id,
            transcript=job.transcript_text,
            rag_collection=req.rag_collection or None,
            rag_top_k=req.rag_top_k,
            rag_embedding_model=req.rag_embedding_model or None,
            rag_embedding_provider=req.rag_embedding_provider or None,
            rag_embedding_api_key=req.rag_embedding_api_key or None,
        )
        print(f"[Step4] 创建任务 | task_id={task_id}")

        # 2. 执行 LangGraph 智能写作流水线（同步，后台线程）
        print(f"[Step4] 开始执行 run_step4_pipeline")
        output = run_step4_pipeline(
            task_id=task_id,
            transcript=job.transcript_text,
            api_key=req.siliconflow_api_key or "",
            ai_provider=req.ai_provider or "siliconflow",
            text_model=req.text_model or "",
            image_provider=req.image_provider or "",
            image_model=req.image_model or "",
            skip_image_generation=req.skip_image_generation,
            article_source_mode=req.article_source_mode,
        )
        print(f"[Step4] 执行完成 | status={output['status']} | image_prompt={output.get('image_prompt', 'None')}")

        if output["status"] == "failed":
            raise RuntimeError(output.get("error", "文章生成失败"))

        # 3. 从 DB 读取最终结果
        task = get_content_task(task_id)
        if not task or not task["article_final"]:
            raise RuntimeError("未能获取到最终文章内容")

        # 4. 填充到 PipelineJob（保持下游兼容）
        job.article_title = task["article_title"] or "AI生成文章"
        job.article_body_markdown = task["article_final"]
        job.article_body_html = task["article_final"]  # Step6 会清洗转换
        
        # 设置图片提示词
        if req.skip_image_generation:
            job.article_image_prompts = []
            print(f"[Step4] skip_image_generation=True，设置 article_image_prompts=[]")
        elif task.get("image_prompt"):
            job.article_image_prompts = [{"id": "cover", "prompt": task["image_prompt"]}]
            print(f"[Step4] 设置 article_image_prompts=[{{'id': 'cover', 'prompt': '{task['image_prompt'][:50]}...'}}]")
        else:
            job.article_image_prompts = []
            print(f"[Step4] task['image_prompt'] 为空，设置 article_image_prompts=[]")

        _finish_step(job, result, data={
            "title": job.article_title,
        })
    except Exception as e:
        if isinstance(e, RuntimeError) and ("暂停" in str(e) or "取消" in str(e) or "删除" in str(e)):
            return
        _fail_step(job, result, f"[Step4-文章] {e}")
        return

    # ── Step 5: 生成封面图 ──────────────────────────────────────────────────
    print(f"[Step5] 检查图片生成 | skip_image_generation={req.skip_image_generation}")
    if req.skip_image_generation:
        print(f"[Step5] skip_image_generation=True，跳过封面图生成，使用默认占位图")
        from app.services.wechat_service import _generate_placeholder_cover
        placeholder = _generate_placeholder_cover()
        job.cover_image_path = str(placeholder)
        pipeline_store.save(job)
    else:
        try:
            result = _begin_step(job, StepName.GENERATE_IMAGE)
        except RuntimeError as e:
            if "暂停" in str(e) or "取消" in str(e) or "删除" in str(e):
                return
            raise
        try:
            image_prompts = getattr(job, 'article_image_prompts', [])
            print(f"[Step5] 开始生成图片 | image_prompts长度={len(image_prompts)}")
            
            if image_prompts:
                output_dir = cfg.outputs_dir / f"{job_id}_images"
                output_dir.mkdir(parents=True, exist_ok=True)

                image_provider = req.image_provider or req.ai_provider or "siliconflow"
                image_api_key = req.image_api_key or req.siliconflow_api_key
                image_model_name = req.image_model or None

                ai_cfg = cfg.get_ai_provider_config(image_provider)
                image_base_url = ai_cfg.get("base_url", cfg.siliconflow_base_url)

                if image_provider == "zhipu":
                    image_size = cfg.zhipu_default_image_size
                    if image_model_name is None:
                        image_model_name = cfg.zhipu_default_image_model
                else:
                    image_size = cfg.siliconflow_default_image_size
                    if image_model_name is None:
                        image_model_name = cfg.siliconflow_default_image_model

                print(f"[Step5] 调用 generate_images_concurrent | provider={image_provider} | model={image_model_name}")
                image_map = generate_images_concurrent(
                    image_prompts=image_prompts,
                    api_key=image_api_key,
                    output_dir=output_dir,
                    model_name=image_model_name,
                    image_size=image_size,
                    base_url=image_base_url,
                    provider=image_provider,
                )
                if "cover" in image_map:
                    job.cover_image_path = str(image_map["cover"])
                print(f"[Step5] 图片生成成功 | cover_image_path={job.cover_image_path}")
            else:
                print(f"[Step5] 警告: image_prompts 为空，使用默认占位图")
                from app.services.wechat_service import _generate_placeholder_cover
                placeholder = _generate_placeholder_cover()
                job.cover_image_path = str(placeholder)

            _finish_step(job, result, data={
                "cover_image_path": job.cover_image_path,
            })
        except Exception as e:
            if isinstance(e, RuntimeError) and ("暂停" in str(e) or "取消" in str(e) or "删除" in str(e)):
                return
            _fail_step(job, result, f"[Step5-生图] {e}")
            return

    # ── Step 6: 替换占位符 + 微信 HTML 清洗 ─────────────────────────────
    try:
        result = _begin_step(job, StepName.CONVERT_HTML)
    except RuntimeError as e:
        if "暂停" in str(e) or "取消" in str(e) or "删除" in str(e):
            return
        raise
    try:
        markdown = job.article_body_markdown
        if not markdown:
            raise ValueError("没有文章 Markdown 内容，无法转换 HTML")

        # Markdown → 微信兼容 HTML（先转 Markdown 再清洗）
        wechat_html = convert_to_wechat_html(markdown, is_markdown=True)

        output_path = (cfg.outputs_dir / f"{job_id}_wechat.html").resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(wechat_html, encoding="utf-8")

        job.article_html = wechat_html
        job.wechat_html_path = str(output_path)
        _finish_step(job, result, data={
            "wechat_html_path": str(output_path),
            "title": job.article_title,
        })
    except Exception as e:
        if isinstance(e, RuntimeError) and ("暂停" in str(e) or "取消" in str(e) or "删除" in str(e)):
            return
        _fail_step(job, result, f"[Step6-HTML] {e}")
        return

    # ── Step 7: 发布草稿 ──────────────────────────────────────────────────
    try:
        result = _begin_step(job, StepName.PUBLISH_DRAFT)
    except RuntimeError as e:
        if "暂停" in str(e) or "取消" in str(e) or "删除" in str(e):
            return
        raise
    try:
        appid = req.wechat_appid or cfg.wechat_appid
        appsecret = req.wechat_appsecret or cfg.wechat_appsecret
        if not appid or not appsecret:
            raise ValueError("微信 AppID / AppSecret 未配置，无法发布草稿")

        resolved_title = req.title or job.article_title or None

        # 封面图路径：优先使用 Step5 生成的图片
        resolved_cover: Path | None = None
        if job.cover_image_path and Path(job.cover_image_path).exists():
            resolved_cover = Path(job.cover_image_path)
            print(f"[Step7] 使用封面图: {resolved_cover}")
        else:
            print(f"[Step7] 封面图不存在或未生成，使用默认占位图")

        wechat_html = Path(job.wechat_html_path).read_text(encoding="utf-8")

        publish_result = publish_draft(
            appid=appid,
            appsecret=appsecret,
            content_html=wechat_html,
            cover_image_path=resolved_cover,
            title=resolved_title,
            author=req.author or None,
            original_notice=req.original_notice or None,
        )

        job.draft_media_id = publish_result["media_id"]
        job.draft_preview_url = publish_result["preview_url"]
        job.status = JobStatus.SUCCESS

        _finish_step(job, result, data={
            "media_id": publish_result["media_id"],
            "preview_url": publish_result["preview_url"],
        })
    except Exception as e:
        if isinstance(e, RuntimeError) and ("暂停" in str(e) or "取消" in str(e) or "删除" in str(e)):
            return
        _fail_step(job, result, f"[Step7-发布] {e}")
