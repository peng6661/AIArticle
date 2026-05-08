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
    → 并发生图+上传微信 → 替换占位符+清洗HTML → 发布草稿+打开浏览器
    """
    job = pipeline_store.create()
    job.share_text = req.share_text
    job.skip_publish = req.skip_publish
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
    from app.services.article_service import generate_article
    from app.services.image_service import generate_images_concurrent, upload_images_to_wechat_concurrent
    from app.services.html_service import convert_to_wechat_html
    from app.services.wechat_service import (
        get_access_token, replace_image_placeholders, publish_draft
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

    # ── Step 4: AI 生成文章（JSON 结构化输出）────────────────────────────
    try:
        result = _begin_step(job, StepName.GENERATE_ARTICLE)
    except RuntimeError as e:
        if "暂停" in str(e) or "取消" in str(e) or "删除" in str(e):
            return
        raise
    try:
        ai_cfg = cfg.get_ai_provider_config(req.ai_provider)
        # ── 打印配置信息，方便调试 ──────────────────────────────────────
        masked_key = (req.siliconflow_api_key[:6] + "****" + req.siliconflow_api_key[-4:]) if req.siliconflow_api_key and len(req.siliconflow_api_key) > 10 else "（空）"
        _text_model = req.text_model or ai_cfg["default_text_model"]
        print(f"\n{'='*60}")
        print(f"[Step4-文章] 配置信息 | job_id={job_id} | ai_provider={req.ai_provider}")
        print(f"  base_url  = {ai_cfg['base_url']}")
        print(f"  api_key   = {masked_key}")
        print(f"  model     = {_text_model}")
        print(f"  temp      = {ai_cfg['default_temperature']}")
        print(f"  max_tokens= {ai_cfg['max_tokens']}")
        print(f"{'='*60}\n")
        article_data = generate_article(
            material_path=Path(job.transcript_path),
            topic=req.topic or None,
            extra_requirements=req.extra_requirements,
            api_key=req.siliconflow_api_key,
            model_name=_text_model,
            temperature=ai_cfg["default_temperature"],
            generate_inline_images=req.generate_inline_images,
            base_url=ai_cfg["base_url"],
            max_tokens=ai_cfg["max_tokens"],
            rag_collection=req.rag_collection or None,
            rag_top_k=req.rag_top_k,
            rag_embedding_model=req.rag_embedding_model or None,
            rag_embedding_provider=req.rag_embedding_provider or None,
        )
        # article_data = {"title": "...", "content": "Markdown格式正文(含图片占位符)", "image_prompts": [...]}
        job.article_title = article_data["title"]
        job.article_body_markdown = article_data["content"]   # content 是 Markdown，存到此字段
        job.article_body_html = article_data["content"]      # 同时写入 HTML 字段（Step6 会清洗转换）
        job.article_image_prompts = article_data["image_prompts"]
        job.generate_inline_images = req.generate_inline_images
        _finish_step(job, result, data={
            "title": article_data["title"],
            "generate_inline_images": req.generate_inline_images,
            "image_count": len(article_data["image_prompts"]),
        })
    except Exception as e:
        if isinstance(e, RuntimeError) and ("暂停" in str(e) or "取消" in str(e) or "删除" in str(e)):
            return
        _fail_step(job, result, f"[Step4-文章] {e}")
        return

    # ── Step 5: 并发生图 + 上传微信素材 ──────────────────────────────────
    try:
        result = _begin_step(job, StepName.GENERATE_IMAGE)
    except RuntimeError as e:
        if "暂停" in str(e) or "取消" in str(e) or "删除" in str(e):
            return
        raise
    try:
        all_prompts = job.article_image_prompts
        generate_inline = req.generate_inline_images

        # 5a. 决定本次实际生成哪些图
        # generate_inline=True  → 生成全部（封面 cover + 文中 img_01...）
        # generate_inline=False → 仅生成封面（id=cover 或第一张）
        if generate_inline:
            prompts_to_generate = all_prompts
        else:
            cover_prompt = next(
                (p for p in all_prompts if p["id"] == "cover"),
                all_prompts[0] if all_prompts else None,
            )
            prompts_to_generate = [cover_prompt] if cover_prompt else []

        if not prompts_to_generate:
            raise ValueError("没有可生成的图片 prompt，请检查 Step4 输出")

        # ── 打印配置信息，方便调试 ──────────────────────────────────────
        _image_model = req.image_model or ai_cfg["default_image_model"]
        _image_size = req.image_size or ai_cfg["default_image_size"]
        print(f"\n{'='*60}")
        print(f"[Step5-配图] 配置信息 | job_id={job_id} | ai_provider={req.ai_provider}")
        print(f"  base_url  = {ai_cfg['base_url']}")
        print(f"  api_key   = {masked_key}")
        print(f"  model     = {_image_model}")
        print(f"  size      = {_image_size}")
        print(f"{'='*60}\n")

        # 5b. 并发生图，下载到本地
        local_map = generate_images_concurrent(
            image_prompts=prompts_to_generate,
            api_key=req.siliconflow_api_key,
            output_dir=cfg.outputs_dir,
            model_name=_image_model,
            image_size=_image_size,
            base_url=ai_cfg["base_url"],
        )

        # 5c. 封面图：优先 id=cover，兜底取第一张
        cover_local_path = local_map.get("cover") or next(iter(local_map.values()), None)
        if cover_local_path:
            job.image_path = str(cover_local_path.resolve())

        # 5d. 只有开启文中插图 且 有微信凭证时，才上传正文图片到微信素材库
        #     cover 图不上传为正文素材（Step7 单独以 thumb 类型上传）
        appid = req.wechat_appid or cfg.wechat_appid
        appsecret = req.wechat_appsecret or cfg.wechat_appsecret
        wechat_upload_map: dict[str, dict] = {}
        if generate_inline and appid and appsecret:
            inline_map = {k: v for k, v in local_map.items() if k != "cover"}
            if inline_map:
                access_token = get_access_token(appid, appsecret)
                wechat_upload_map = upload_images_to_wechat_concurrent(
                    local_image_map=inline_map, access_token=access_token,
                )

        # 5e. 合并结果
        combined: dict[str, dict] = {
            img_id: {
                "local_path": str(lp.resolve()),
                "wechat_url": wechat_upload_map.get(img_id, {}).get("wechat_url", ""),
                "media_id": wechat_upload_map.get(img_id, {}).get("media_id", ""),
            }
            for img_id, lp in local_map.items()
        }
        job.wechat_image_map = combined

        _finish_step(job, result, data={
            "generate_inline_images": generate_inline,
            "cover_path": job.image_path,
            "image_count": len(combined),
            "uploaded_to_wechat": bool(wechat_upload_map),
        })
    except Exception as e:
        if isinstance(e, RuntimeError) and ("暂停" in str(e) or "取消" in str(e) or "删除" in str(e)):
            return
        _fail_step(job, result, f"[Step5-配图] {e}")
        return

    # ── Step 6: 替换占位符 + 微信 HTML 清洗 ─────────────────────────────
    try:
        result = _begin_step(job, StepName.CONVERT_HTML)
    except RuntimeError as e:
        if "暂停" in str(e) or "取消" in str(e) or "删除" in str(e):
            return
        raise
    try:
        html = job.article_body_html

        if req.generate_inline_images and job.wechat_image_map:
            # 将 【图片占位符：img_01】 替换为微信域 <img src="..."> 标签
            html = replace_image_placeholders(html, job.wechat_image_map)
        # generate_inline_images=False 时，article_body_html 已无占位符（Step4 已清除），直接清洗

        # Markdown → 微信兼容 HTML（先转 Markdown 再清洗）
        wechat_html = convert_to_wechat_html(html, is_markdown=True)

        output_path = (cfg.outputs_dir / f"{job_id}_wechat.html").resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(wechat_html, encoding="utf-8")

        job.article_html = wechat_html
        job.wechat_html_path = str(output_path)
        _finish_step(job, result, data={
            "wechat_html_path": str(output_path),
            "title": job.article_title,
            "generate_inline_images": req.generate_inline_images,
        })
    except Exception as e:
        if isinstance(e, RuntimeError) and ("暂停" in str(e) or "取消" in str(e) or "删除" in str(e)):
            return
        _fail_step(job, result, f"[Step6-HTML] {e}")
        return

    # ── Step 7: 发布草稿 ──────────────────────────────────────────────────
    if req.skip_publish:
        job.status = JobStatus.SUCCESS
        pipeline_store.save(job)
        return

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

        wechat_html = Path(job.wechat_html_path).read_text(encoding="utf-8")
        resolved_title = req.title or job.article_title or None

        publish_result = publish_draft(
            appid=appid,
            appsecret=appsecret,
            content_html=wechat_html,
            cover_image_path=Path(job.image_path),
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
