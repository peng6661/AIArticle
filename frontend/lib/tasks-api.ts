import apiClient from "@/lib/api-client";
import axios from "axios";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
import {
  FullPipelineRequest,
  FullPipelineResponse,
  JobListResponse,
  JobStatusResponse,
} from "@/types/task";

export const taskApi = {
  runFullPipeline: async (
    req: FullPipelineRequest
  ): Promise<FullPipelineResponse> => {
    const { data } = await apiClient.post<FullPipelineResponse>(
      "/pipeline/run",
      req
    );
    return data;
  },

  listJobs: async (): Promise<JobListResponse> => {
    const { data } = await apiClient.get<JobListResponse>("/pipeline/jobs");
    return data;
  },

  getJobStatus: async (jobId: string): Promise<JobStatusResponse> => {
    const { data } = await apiClient.get<JobStatusResponse>(
      `/pipeline/jobs/${jobId}`
    );
    return data;
  },

  deleteJob: async (
    jobId: string
  ): Promise<{ message: string }> => {
    const { data } = await apiClient.delete(`/pipeline/jobs/${jobId}`);
    return data;
  },

  batchDeleteJobs: async (
    jobIds: string[]
  ): Promise<{ message: string; deleted_count: number; deleted_job_ids: string[] }> => {
    const { data } = await apiClient.post("/pipeline/jobs/batch-delete", {
      job_ids: jobIds,
    });
    return data;
  },

  retryFailedJob: async (
    jobId: string,
    params: {
      api_key?: string;
      wechat_appid?: string;
      wechat_appsecret?: string;
    }
  ) => {
    const { data } = await apiClient.post(
      `/pipeline/jobs/${jobId}/retry`,
      params
    );
    return data;
  },

  pauseJob: async (
    jobId: string
  ): Promise<{ success: boolean; message: string; job_id: string }> => {
    const { data } = await apiClient.post(`/pipeline/jobs/${jobId}/pause`);
    return data;
  },

  resumeJob: async (
    jobId: string,
    params: {
      api_key?: string;
      wechat_appid?: string;
      wechat_appsecret?: string;
    }
  ) => {
    const { data } = await apiClient.post(
      `/pipeline/jobs/${jobId}/resume`,
      params
    );
    return data;
  },

  // ── 上传本地视频（跳过下载步骤，从 Step2 音频提取开始）──────────────────
  uploadVideo: async (
    file: File,
    onProgress?: (percent: number) => void,
    signal?: AbortSignal,
  ): Promise<{ success: boolean; message: string; job_id: string }> => {
    const formData = new FormData();
    formData.append("video", file);

    const { data } = await axios.post<{ success: boolean; message: string; job_id: string }>(
      `${API_BASE}/pipeline/upload-video`,
      formData,
      {
        headers: { "Content-Type": "multipart/form-data" },
        signal,
        onUploadProgress: (ev) => {
          if (onProgress && ev.total) {
            onProgress(Math.round((ev.loaded / ev.total) * 100));
          }
        },
        // 大文件上传超时放宽到 10 分钟
        timeout: 10 * 60 * 1000,
      },
    );
    return data;
  },

  // ── 重试各步骤 ──────────────────────────────────────────────

  /** 重试 Step1: 下载视频 */
  retryDownload: async (
    jobId: string,
    shareText: string
  ) => {
    const { data } = await apiClient.post("/pipeline/step/download", {
      job_id: jobId,
      share_text: shareText,
    });
    return data;
  },

  /** 重试 Step2: 提取音频 */
  retryExtractAudio: async (
    jobId: string,
    audioFormat: string = "mp3"
  ) => {
    const { data } = await apiClient.post("/pipeline/step/extract_audio", {
      job_id: jobId,
      audio_format: audioFormat,
    });
    return data;
  },

  /** 重试 Step3: 语音转写 */
  retryTranscribe: async (
    jobId: string,
    modelSize: string = "small",
    language: string = "zh"
  ) => {
    const { data } = await apiClient.post("/pipeline/step/transcribe", {
      job_id: jobId,
      model_size: modelSize,
      language,
    });
    return data;
  },

  /** 重试 Step4: AI生成文章 */
  retryGenerateArticle: async (
    jobId: string,
    params: {
      api_key: string;
      topic?: string;
      extra_requirements?: string;
      text_model?: string;
      temperature?: number;
      generate_inline_images?: boolean;
    }
  ) => {
    const { data } = await apiClient.post(
      "/pipeline/step/generate_article",
      { job_id: jobId, ...params }
    );
    return data;
  },

  /** 重试 Step5: 并发生图 + 上传微信素材 */
  retryGenerateImage: async (
    jobId: string,
    params: {
      api_key: string;
      wechat_appid?: string;
      wechat_appsecret?: string;
      image_model?: string;
      image_size?: string;
      generate_inline_images?: boolean;
    }
  ) => {
    const { data } = await apiClient.post(
      "/pipeline/step/generate_image",
      { job_id: jobId, ...params }
    );
    return data;
  },

  /** 重试 Step6: 转换HTML */
  retryConvertHtml: async (jobId: string) => {
    const { data } = await apiClient.post("/pipeline/step/convert_html", {
      job_id: jobId,
    });
    return data;
  },

  /** 重试 Step7: 发布草稿 */
  retryPublishDraft: async (
    jobId: string,
    params: {
      appid?: string;
      appsecret?: string;
      title?: string;
      author?: string;
      digest?: string;
      content_source_url?: string;
      original_notice?: string;
    }
  ) => {
    const { data } = await apiClient.post(
      "/pipeline/step/publish_draft",
      { job_id: jobId, ...params }
    );
    return data;
  },
};
