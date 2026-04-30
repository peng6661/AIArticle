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
  share_text: string | null;
  video_path: string | null;
  audio_path: string | null;
  transcript_path: string | null;
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
}

export interface FullPipelineResponse {
  success: boolean;
  message: string;
  job_id: string;
}

export function calculateProgress(job: JobStatusResponse): number {
  if (job.status === JobStatus.SUCCESS) return 100;
  if (job.status === JobStatus.PENDING) return 0;
  // PAUSED / RUNNING / FAILED 都按已完成步骤计算
  const completed = job.steps.filter(
    (s) => s.status === JobStatus.SUCCESS
  ).length;
  return Math.round((completed / STEP_ORDER.length) * 100);
}
