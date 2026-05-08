export enum JobStatus {
  PENDING = "pending",
  RUNNING = "running",
  PAUSED = "paused",
  CANCELLED = "cancelled",
  SUCCESS = "success",
  FAILED = "failed",
}

export enum StepName {
  DOWNLOAD = "download",
  EXTRACT_AUDIO = "extract_audio",
  TRANSCRIBE = "transcribe",
  GENERATE_ARTICLE = "generate_article",
  GENERATE_IMAGE = "generate_image",
  CONVERT_HTML = "convert_html",
  PUBLISH_DRAFT = "publish_draft",
}

export const STEP_LABELS: Record<string, string> = {
  [StepName.DOWNLOAD]: "下载视频",
  [StepName.EXTRACT_AUDIO]: "提取音频",
  [StepName.TRANSCRIBE]: "语音转写",
  [StepName.GENERATE_ARTICLE]: "生成文章",
  [StepName.GENERATE_IMAGE]: "生成配图",
  [StepName.CONVERT_HTML]: "转换HTML",
  [StepName.PUBLISH_DRAFT]: "发布草稿",
};

export const STEP_ORDER: string[] = [
  StepName.DOWNLOAD,
  StepName.EXTRACT_AUDIO,
  StepName.TRANSCRIBE,
  StepName.GENERATE_ARTICLE,
  StepName.GENERATE_IMAGE,
  StepName.CONVERT_HTML,
  StepName.PUBLISH_DRAFT,
];

export function getVisibleStepOrder(job: Pick<JobStatusResponse, "skip_publish">): string[] {
  if (job.skip_publish) {
    return STEP_ORDER.filter((step) => step !== StepName.PUBLISH_DRAFT);
  }
  return STEP_ORDER;
}

export interface StepResult {
  step: string;
  status: string;
  message: string;
  data: Record<string, any>;
  started_at: string;
  finished_at: string | null;
}

export interface JobStatusResponse {
  job_id: string;
  status: JobStatus;
  current_step: string | null;
  steps: StepResult[];
  skip_publish: boolean;
  share_text: string | null;
  video_path: string | null;
  audio_path: string | null;
  transcript_path: string | null;
  article_body_markdown: string | null;  // 生成的 Markdown 文章
  article_html: string | null;
  wechat_html_path: string | null;
  image_path: string | null;
  // Instagram 多图帖子支持
  media_type: string | null;
  image_count: number;
  image_paths: string[];
  image_urls: string[];
  draft_media_id: string | null;
  draft_preview_url: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobListResponse {
  total: number;
  jobs: JobStatusResponse[];
}

export interface FullPipelineRequest {
  share_text: string;
  siliconflow_api_key: string;
  wechat_appid?: string;
  wechat_appsecret?: string;
  ai_provider?: "siliconflow" | "zhipu";
  topic?: string;
  extra_requirements?: string;
  text_model?: string;
  image_model?: string;
  image_size?: string;
  audio_format?: string;
  transcribe_model?: string;
  language?: string;
  author?: string;
  title?: string;
  original_notice?: string;
  generate_inline_images?: boolean;
  skip_publish?: boolean;
  rag_collection?: string;
  rag_top_k?: number;
  rag_embedding_model?: string;
  rag_embedding_provider?: string;
}

export interface FullPipelineResponse {
  success: boolean;
  message: string;
  job_id: string;
}

export function calculateProgress(job: JobStatusResponse): number {
  if (job.status === JobStatus.SUCCESS) return 100;
  if (job.status === JobStatus.PENDING) return 0;
  if (job.status === JobStatus.CANCELLED) return 0;

  const totalSteps = getVisibleStepOrder(job).length;

  // 统计各状态步骤（兼容 steps 为空但 current_step 已设置的竞态场景）
  let completed = 0;
  let running = 0;
  for (const s of job.steps) {
    if (s.status === JobStatus.SUCCESS) {
      completed += 1;
    } else if (s.status === JobStatus.RUNNING) {
      running += 1;
    } else if (s.status === JobStatus.FAILED) {
      // 失败步骤也算已推进（后续可重试）
      completed += 1;
    }
  }

  // 已完成步骤全算 + 正在运行的步骤给 50% 权重
  let progress = Math.round(((completed + running * 0.5) / totalSteps) * 100);

  // RUNNING 状态保底 ≥5%，避免任务已启动但步骤尚未写入 DB 时进度条卡在 0%
  if (job.status === JobStatus.RUNNING && progress < 5) {
    progress = 5;
  }
  // PAUSED 状态保底：至少显示已完成的进度
  if (job.status === JobStatus.PAUSED && progress < 5 && completed > 0) {
    progress = 5;
  }

  return Math.min(progress, 100);
}
