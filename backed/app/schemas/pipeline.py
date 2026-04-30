"""
Pydantic 请求/响应模型
"""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from app.core.pipeline import JobStatus, StepName


# ── 通用响应 ────────────────────────────────────────────────────────────────

class BaseResponse(BaseModel):
    success: bool
    message: str = ""
    data: dict[str, Any] | None = None


class RetryJobRequest(BaseModel):
    api_key: str = Field("", description="SiliconFlow API Key，文章/生图重试时使用")
    wechat_appid: str = Field("", description="公众号 AppID，发布/上传素材重试时使用")
    wechat_appsecret: str = Field("", description="公众号 AppSecret，发布/上传素材重试时使用")


class RetryJobResponse(BaseResponse):
    job_id: str = ""
    retried_step: str = ""


class BatchDeleteJobsRequest(BaseModel):
    job_ids: list[str] = Field(default_factory=list, description="需要批量删除的 job_id 列表")


class BatchDeleteJobsResponse(BaseResponse):
    deleted_count: int = 0
    deleted_job_ids: list[str] = Field(default_factory=list)


# ── Step 1: 全平台视频下载 ─────────────────────────────────────────────────

class DownloadRequest(BaseModel):
    share_text: str = Field(..., description="分享文本（支持抖音/Instagram/B站/TikTok/快手/X/YouTube）")
    job_id: str = Field("", description="重试时传入已存在的 job_id，留空则创建新任务")


class DownloadResponse(BaseResponse):
    job_id: str = ""
    video_path: str = ""
    video_title: str = ""
    # Instagram 多图帖子支持
    media_type: str = Field("", description="媒体类型: video / image")
    image_count: int = Field(0, description="图片数量（Instagram 多图时 > 1）")
    image_paths: list[str] = Field(default_factory=list, description="所有下载的图片本地路径")
    image_urls: list[str] = Field(default_factory=list, description="所有图片的原始 URL")


# ── Step 2: 提取音频 ────────────────────────────────────────────────────────

class ExtractAudioRequest(BaseModel):
    job_id: str = Field(..., description="上一步返回的 job_id")
    audio_format: str = Field("mp3", description="输出格式: mp3 / wav")


class ExtractAudioResponse(BaseResponse):
    job_id: str = ""
    audio_path: str = ""


# ── Step 3: 语音转写 ────────────────────────────────────────────────────────

class TranscribeRequest(BaseModel):
    job_id: str = Field(..., description="job_id")
    model_size: str = Field("small", description="模型: tiny/base/small/medium/large-v3")
    language: str = Field("zh", description="语言代码")
    device: str = Field("", description="转写设备: auto/cpu/cuda（留空用 config 默认值）")
    compute_type: str = Field("", description="计算精度: auto/int8/float16（留空用 config 默认值）")


class TranscribeResponse(BaseResponse):
    job_id: str = ""
    transcript_path: str = ""
    transcript_preview: str = Field("", description="前 200 字预览")


class PauseJobResponse(BaseModel):
    success: bool
    message: str
    job_id: str


class ResumeJobRequest(BaseModel):
    api_key: str = Field("", description="SiliconFlow API Key，后续步骤可能需要")
    wechat_appid: str = Field("", description="公众号 AppID，发布步骤需要")
    wechat_appsecret: str = Field("", description="公众号 AppSecret")


# ── Step 4: 生成文章（JSON 结构化）─────────────────────────────────────────

class GenerateArticleRequest(BaseModel):
    job_id: str = Field(..., description="job_id")
    api_key: str = Field(..., description="SiliconFlow API Key")
    topic: str = Field("", description="文章主题，留空使用默认")
    extra_requirements: str = Field("", description="额外写作要求")
    text_model: str = Field("", description="文章生成模型，留空使用默认")
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    generate_inline_images: bool = Field(
        True,
        description=(
            "是否在文章正文中生成插图。"
            "True=AI 在正文插入占位符，后续步骤生成并替换为真实图片；"
            "False=正文纯文字，封面图仍会生成。"
        ),
    )


class GenerateArticleResponse(BaseResponse):
    job_id: str = ""
    article_title: str = Field("", description="AI 生成的文章标题")
    image_count: int = Field(0, description="文章中图片占位符数量")
    content_preview: str = Field("", description="正文前 300 字")


# ── Step 5: 并发生图 + 上传微信素材 ────────────────────────────────────────

class GenerateImageRequest(BaseModel):
    job_id: str = Field(..., description="job_id")
    api_key: str = Field(..., description="SiliconFlow API Key（生图用）")
    wechat_appid: str = Field("", description="公众号 AppID，用于上传素材；留空则只下载到本地不上传")
    wechat_appsecret: str = Field("", description="公众号 AppSecret")
    image_model: str = Field("", description="图片模型，留空使用默认")
    image_size: str = Field("", description="图片尺寸，留空使用默认")
    generate_inline_images: bool = Field(
        True,
        description=(
            "是否生成文章正文中的插图。"
            "True=生成全部图片（封面+文中插图）并上传微信素材替换占位符；"
            "False=仅生成封面图，正文占位符将被自动移除。"
        ),
    )


class GenerateImageResponse(BaseResponse):
    job_id: str = ""
    image_count: int = Field(0, description="生成图片数量")
    image_path: str = Field("", description="封面图本地路径")


# ── Step 6: 替换占位符 + 微信 HTML 清洗 ────────────────────────────────────

class ConvertHtmlRequest(BaseModel):
    job_id: str = Field(..., description="job_id")


class ConvertHtmlResponse(BaseResponse):
    job_id: str = ""
    wechat_html_path: str = ""
    title: str = ""
    html_preview: str = Field("", description="HTML 前 500 字预览")


# ── Step 7: 发布草稿 ────────────────────────────────────────────────────────

class PublishDraftRequest(BaseModel):
    job_id: str = Field(..., description="job_id")
    appid: str = Field("", description="公众号 AppID，留空读环境变量")
    appsecret: str = Field("", description="公众号 AppSecret，留空读环境变量")
    title: str = Field("", description="覆盖文章标题，留空使用 AI 生成的标题")
    author: str = Field("", description="作者，留空使用配置默认")
    digest: str = Field("", description="摘要")
    content_source_url: str = Field("", description="原文链接")
    original_notice: str = Field("", description="原创声明，留空使用配置默认")


class PublishDraftResponse(BaseResponse):
    job_id: str = ""
    media_id: str = ""
    preview_url: str = ""


# ── 视频上传（跳过 Step1，从 Step2 开始）─────────────────────────────────

class UploadVideoResponse(BaseResponse):
    job_id: str = ""


# ── 一键全流程 ──────────────────────────────────────────────────────────────

class FullPipelineRequest(BaseModel):
    share_text: str = Field(..., description="分享文本（支持抖音/Instagram/B站/TikTok/快手/X/YouTube）")
    siliconflow_api_key: str = Field(..., description="SiliconFlow API Key（文章+生图）")
    wechat_appid: str = Field("", description="公众号 AppID")
    wechat_appsecret: str = Field("", description="公众号 AppSecret")
    topic: str = Field("", description="文章主题")
    extra_requirements: str = Field("", description="额外写作要求")
    text_model: str = Field("", description="文章模型")
    image_model: str = Field("", description="图片模型")
    image_size: str = Field("", description="图片尺寸")
    audio_format: str = Field("mp3")
    transcribe_model: str = Field("small")
    language: str = Field("zh")
    transcribe_device: str = Field("", description="转写设备: auto/cpu/cuda")
    transcribe_compute_type: str = Field("", description="计算精度: auto/int8/float16")
    author: str = Field("", description="公众号作者")
    title: str = Field("", description="覆盖文章标题")
    original_notice: str = Field("", description="原创声明")
    generate_inline_images: bool = Field(
        True,
        description=(
            "是否生成文章正文插图。"
            "True=生成全部图片（封面+文中插图）并上传微信素材替换占位符；"
            "False=仅生成封面图，正文占位符将被自动移除。"
        ),
    )
    skip_publish: bool = Field(False, description="是否跳过发布步骤（仅生成不发布）")


class FullPipelineResponse(BaseResponse):
    job_id: str = ""


# ── Job 状态查询 ────────────────────────────────────────────────────────────

class StepResultSchema(BaseModel):
    step: str
    status: str
    message: str
    data: dict[str, Any] = {}
    started_at: str
    finished_at: str | None


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    current_step: str | None
    steps: list[StepResultSchema]
    share_text: str | None
    video_path: str | None
    audio_path: str | None
    transcript_path: str | None
    article_html: str | None          # 最终微信 HTML 预览（截断）
    wechat_html_path: str | None
    image_path: str | None            # 封面图路径
    # Instagram 多图帖子支持
    media_type: str | None = None     # video / image
    image_count: int = 0              # 图片数量
    image_paths: list[str] = Field(default_factory=list, description="所有下载的图片本地路径")
    image_urls: list[str] = Field(default_factory=list, description="所有图片的原始 URL")
    draft_media_id: str | None
    draft_preview_url: str | None
    error: str | None
    created_at: str
    updated_at: str
