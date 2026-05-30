"""
Pydantic 请求/响应模型
"""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from app.core.pipeline import JobStatus, StepName


# ── 通用响应 ────────────────────────────────────────────────────────────────

class BaseResponse(BaseModel):
    success: bool
    message: str = ""
    data: dict[str, Any] | None = None


class RetryJobRequest(BaseModel):
    api_key: str = Field("", description="AI 服务 API Key（SiliconFlow 或智谱），文章生成重试时使用")
    ai_provider: str = Field("siliconflow", description="AI 服务提供商: siliconflow | zhipu")
    text_model: str = Field("", description="文章生成模型，留空使用 provider 默认")
    image_provider: str = Field("", description="图片生成服务商: siliconflow | zhipu，留空跟随 ai_provider")
    image_api_key: str = Field("", description="图片生成专用 API Key，留空使用 api_key")
    image_model: str = Field("", description="图片生成模型，留空使用 image_provider 默认")
    skip_image_generation: bool = Field(False, description="是否跳过封面图生成")
    article_source_mode: str = Field("video_transcript", description="文章生成模式: video_transcript | text_rewrite")
    wechat_appid: str = Field("", description="公众号 AppID，发布/上传素材重试时使用")
    wechat_appsecret: str = Field("", description="公众号 AppSecret，发布/上传素材重试时使用")
    rag_collection: str = Field("", description="RAG 知识库集合名，留空不使用 RAG")
    rag_top_k: int = Field(5, description="RAG 检索返回的相关块数量", ge=1, le=20)
    rag_embedding_model: str = Field("", description="RAG 向量模型，留空使用 config 默认值")
    rag_embedding_provider: str = Field("", description="向量模型服务商: siliconflow | zhipu，留空使用 config 默认值")
    rag_embedding_api_key: str = Field("", description="RAG 向量模型专用 API Key，留空则使用主 api_key")


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
    share_text: str = Field(..., min_length=1, description="分享文本（支持抖音/Instagram/B站/TikTok/快手/X/YouTube）")
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
    model_config = ConfigDict(protected_namespaces=())

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
    api_key: str = Field("", description="AI 服务 API Key（SiliconFlow 或智谱），后续步骤可能需要")
    ai_provider: str = Field("siliconflow", description="AI 服务提供商: siliconflow | zhipu")
    text_model: str = Field("", description="文章生成模型，留空使用 provider 默认")
    image_provider: str = Field("", description="图片生成服务商: siliconflow | zhipu，留空跟随 ai_provider")
    image_api_key: str = Field("", description="图片生成专用 API Key，留空使用 api_key")
    image_model: str = Field("", description="图片生成模型，留空使用 image_provider 默认")
    skip_image_generation: bool = Field(False, description="是否跳过封面图生成")
    article_source_mode: str = Field("video_transcript", description="文章生成模式: video_transcript | text_rewrite")
    wechat_appid: str = Field("", description="公众号 AppID，发布步骤需要")
    wechat_appsecret: str = Field("", description="公众号 AppSecret")
    rag_collection: str = Field("", description="RAG 知识库集合名，留空不使用 RAG")
    rag_top_k: int = Field(5, description="RAG 检索返回的相关块数量", ge=1, le=20)
    rag_embedding_model: str = Field("", description="RAG 向量模型，留空使用 config 默认值")
    rag_embedding_provider: str = Field("", description="向量模型服务商: siliconflow | zhipu，留空使用 config 默认值")
    rag_embedding_api_key: str = Field("", description="RAG 向量模型专用 API Key，留空则使用主 api_key")





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


# ── 文案上传（跳过 Step1-3，从 Step4 开始）─────────────────────────────

class UploadTextResponse(BaseResponse):
    job_id: str = ""


# ── 一键全流程 ──────────────────────────────────────────────────────────────

class FullPipelineRequest(BaseModel):
    share_text: str = Field(..., min_length=1, description="分享文本（支持抖音/Instagram/B站/TikTok/快手/X/YouTube）")
    siliconflow_api_key: str = Field(..., description="AI 服务 API Key（文章+生图）；SiliconFlow 或智谱均使用此字段")
    wechat_appid: str = Field("", description="公众号 AppID")
    wechat_appsecret: str = Field("", description="公众号 AppSecret")
    ai_provider: str = Field("siliconflow", description="AI 服务提供商: siliconflow | zhipu")
    image_provider: str = Field("", description="图片生成服务商: siliconflow | zhipu，留空跟随 ai_provider")
    image_api_key: str = Field("", description="图片生成专用 API Key，留空使用 siliconflow_api_key")
    image_model: str = Field("", description="图片生成模型，留空使用 image_provider 默认")
    topic: str = Field("", description="文章主题")
    extra_requirements: str = Field("", description="额外写作要求")
    text_model: str = Field("", description="文章模型，留空使用 provider 默认")
    audio_format: str = Field("mp3")
    transcribe_model: str = Field("small")
    language: str = Field("zh")
    transcribe_device: str = Field("", description="转写设备: auto/cpu/cuda")
    transcribe_compute_type: str = Field("", description="计算精度: auto/int8/float16")
    author: str = Field("", description="公众号作者")
    title: str = Field("", description="覆盖文章标题")
    original_notice: str = Field("", description="原创声明")
    skip_image_generation: bool = Field(False, description="是否跳过封面图生成")
    article_source_mode: str = Field("video_transcript", description="文章生成模式: video_transcript | text_rewrite")
    rag_collection: str = Field("", description="RAG 知识库集合名，留空不使用 RAG")
    rag_top_k: int = Field(5, description="RAG 检索返回的相关块数量", ge=1, le=20)
    rag_embedding_model: str = Field("", description="RAG 向量模型，留空使用 config 默认值")
    rag_embedding_provider: str = Field("", description="向量模型服务商: siliconflow | zhipu，留空使用 config 默认值")
    rag_embedding_api_key: str = Field("", description="RAG 向量模型专用 API Key，留空则使用主 api_key")


class FullPipelineResponse(BaseResponse):
    job_id: str = ""


# ── 再次生成（复用文案，直接从 Step4 开始）────────────────────────────────

class RegenerateJobRequest(BaseModel):
    api_key: str = Field(..., description="AI 服务 API Key（SiliconFlow 或智谱）")
    ai_provider: str = Field("siliconflow", description="AI 服务提供商: siliconflow | zhipu")
    text_model: str = Field("", description="文章生成模型，留空使用 provider 默认")
    image_provider: str = Field("", description="图片生成服务商: siliconflow | zhipu，留空跟随 ai_provider")
    image_api_key: str = Field("", description="图片生成专用 API Key，留空使用 api_key")
    image_model: str = Field("", description="图片生成模型，留空使用 image_provider 默认")
    skip_image_generation: bool = Field(False, description="是否跳过封面图生成")
    article_source_mode: str = Field("video_transcript", description="文章生成模式: video_transcript | text_rewrite")
    wechat_appid: str = Field("", description="公众号 AppID")
    wechat_appsecret: str = Field("", description="公众号 AppSecret")
    rag_collection: str = Field("", description="RAG 知识库集合名，留空不使用 RAG")
    rag_top_k: int = Field(5, description="RAG 检索返回的相关块数量", ge=1, le=20)
    rag_embedding_model: str = Field("", description="RAG 向量模型，留空使用 config 默认值")
    rag_embedding_provider: str = Field("", description="向量模型服务商: siliconflow | zhipu，留空使用 config 默认值")
    rag_embedding_api_key: str = Field("", description="RAG 向量模型专用 API Key，留空则使用主 api_key")


class RegenerateJobResponse(BaseResponse):
    job_id: str = ""
    message: str = ""


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
    skip_image_generation: bool = False
    share_text: str | None
    video_path: str | None
    audio_path: str | None
    transcript_path: str | None
    article_body_markdown: str | None  # 生成的 Markdown 文章内容
    article_html: str | None          # 最终微信 HTML 预览（截断）
    wechat_html_path: str | None
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
