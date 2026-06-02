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
      ai_provider?: string;
      text_model?: string;
      image_provider?: string;
      image_api_key?: string;
      image_model?: string;
      wechat_appid?: string;
      wechat_appsecret?: string;
      rag_collection?: string;
      rag_top_k?: number;
      rag_embedding_model?: string;
      rag_embedding_provider?: string;
      rag_embedding_api_key?: string;
      skip_image_generation?: boolean;
      article_source_mode?: "video_transcript" | "text_rewrite";
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
      ai_provider?: string;
      text_model?: string;
      image_provider?: string;
      image_api_key?: string;
      image_model?: string;
      wechat_appid?: string;
      wechat_appsecret?: string;
      skip_image_generation?: boolean;
      rag_collection?: string;
      rag_top_k?: number;
      rag_embedding_model?: string;
      rag_embedding_provider?: string;
      rag_embedding_api_key?: string;
      article_source_mode?: "video_transcript" | "text_rewrite";
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
    skip_image_generation: boolean = false,
    onProgress?: (percent: number) => void,
    signal?: AbortSignal,
  ): Promise<{ success: boolean; message: string; job_id: string }> => {
    const formData = new FormData();
    formData.append("video", file);
    formData.append("skip_image_generation", String(skip_image_generation));

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

  // ── 上传文案（跳过 Step1-3，从 Step4 文章生成开始）─────────────────────
  uploadText: async (
    file: File,
    skip_image_generation: boolean = false,
    onProgress?: (percent: number) => void,
    signal?: AbortSignal,
  ): Promise<{ success: boolean; message: string; job_id: string }> => {
    const formData = new FormData();
    formData.append("text_file", file);
    formData.append("skip_image_generation", String(skip_image_generation));

    const { data } = await axios.post<{ success: boolean; message: string; job_id: string }>(
      `${API_BASE}/pipeline/upload-text`,
      formData,
      {
        headers: { "Content-Type": "multipart/form-data" },
        signal,
        onUploadProgress: (ev) => {
          if (onProgress && ev.total) {
            onProgress(Math.round((ev.loaded / ev.total) * 100));
          }
        },
        // 文案上传超时放宽到 10 分钟
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

  // ── 再次生成（复用文案，从 Step4 开始）─────────────────────────────────────

  /** 再次生成：基于已完成任务创建新任务，复用文本文案直接从文章生成开始 */
  regenerateJob: async (
    originalJobId: string,
    params: {
      api_key: string;
      ai_provider?: string;
      text_model?: string;
      image_provider?: string;
      image_api_key?: string;
      image_model?: string;
      image_size?: string;
      skip_image_generation?: boolean;
      wechat_appid?: string;
      wechat_appsecret?: string;
      rag_collection?: string;
      rag_top_k?: number;
      rag_embedding_model?: string;
      rag_embedding_provider?: string;
      rag_embedding_api_key?: string;
      article_source_mode?: "video_transcript" | "text_rewrite";
    }
  ) => {
    const { data } = await apiClient.post(
      `/pipeline/jobs/${originalJobId}/regenerate`,
      params
    );
    return data;
  },

  // ── 知识库管理 ──────────────────────────────────────────────

  /** 获取知识库集合列表 */
  listCollections: async (): Promise<{ success: boolean; data: { collections: KnowledgeCollection[]; total: number } }> => {
    const { data } = await apiClient.get("/api/knowledge/collections");
    return data;
  },

  /** 创建知识库集合 */
  createCollection: async (name: string, description: string = "") => {
    const { data } = await apiClient.post("/api/knowledge/collections", { name, description });
    return data;
  },

  /** 删除知识库集合 */
  deleteCollection: async (collectionId: number) => {
    const { data } = await apiClient.delete(`/api/knowledge/collections/${collectionId}`);
    return data;
  },

  /** 上传文本/Markdown 文档 */
  ingestText: async (collectionName: string, content: string, title: string, sourceType: string, apiKey: string, embeddingModel: string = "", embeddingProvider: string = "") => {
    const { data } = await apiClient.post("/api/knowledge/documents/text", {
      collection_name: collectionName,
      content,
      title,
      source_type: sourceType,
      api_key: apiKey,
      embedding_model: embeddingModel || undefined,
      embedding_provider: embeddingProvider || undefined,
    });
    return data;
  },

  /** 上传 PDF 文件 */
  ingestPdf: async (collectionName: string, file: File, apiKey: string, title: string = "", embeddingModel: string = "", embeddingProvider: string = "") => {
    const formData = new FormData();
    formData.append("collection_name", collectionName);
    formData.append("api_key", apiKey);
    formData.append("title", title);
    if (embeddingModel) formData.append("embedding_model", embeddingModel);
    if (embeddingProvider) formData.append("embedding_provider", embeddingProvider);
    formData.append("file", file);
    const { data } = await axios.post(`${API_BASE}/api/knowledge/documents/pdf`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 5 * 60 * 1000,
    });
    return data;
  },

  /** 从 pipeline 任务导入 */
  ingestFromJob: async (collectionName: string, jobId: string, apiKey: string, embeddingModel: string = "", embeddingProvider: string = "") => {
    const { data } = await apiClient.post("/api/knowledge/documents/from-job", {
      collection_name: collectionName,
      job_id: jobId,
      api_key: apiKey,
      embedding_model: embeddingModel || undefined,
      embedding_provider: embeddingProvider || undefined,
    });
    return data;
  },

  /** 获取文档列表 */
  listDocuments: async (collectionName: string) => {
    const { data } = await apiClient.get(`/api/knowledge/documents?collection_name=${encodeURIComponent(collectionName)}`);
    return data;
  },

  /** 删除文档 */
  deleteDocument: async (docId: number, collectionName: string) => {
    const { data } = await apiClient.delete(`/api/knowledge/documents/${docId}?collection_name=${encodeURIComponent(collectionName)}`);
    return data;
  },

  /** 测试 RAG 检索 */
  searchKnowledge: async (collectionName: string, query: string, apiKey: string, topK: number = 5, embeddingModel: string = "", embeddingProvider: string = "") => {
    const { data } = await apiClient.post("/api/knowledge/search", {
      collection_name: collectionName,
      query,
      api_key: apiKey,
      top_k: topK,
      embedding_model: embeddingModel || undefined,
      embedding_provider: embeddingProvider || undefined,
    });
    return data;
  },

  // ── 多平台视频搜索 ──────────────────────────────────────────────

  /** 获取搜索支持的平台列表 */
  listSearchPlatforms: async (): Promise<{ success: boolean; platforms: { id: string; name: string }[] }> => {
    const { data } = await apiClient.get("/api/video/search/platforms");
    return data;
  },

  /** 多平台视频搜索（超时 3 分钟，多平台并发较慢） */
  searchVideos: async (
    keyword: string,
    platforms: string[],
    limit: number = 10
  ): Promise<{
    success: boolean;
    keyword: string;
    results: Record<string, VideoSearchResult[]>;
    errors: string[];
  }> => {
    const { data } = await apiClient.post("/api/video/search", {
      keyword,
      platforms,
      limit,
    }, { timeout: 180000 });
    return data;
  },

  listResourceItems: async (
    params: { keyword?: string; netdiskType?: string; page?: number; pageSize?: number } = {}
  ): Promise<ResourceListResponse> => {
    const { data } = await apiClient.get("/api/resource-library", { params });
    return data;
  },

  listResourceNetdiskTypes: async (): Promise<{ success: boolean; data: ResourceNetdiskType[] }> => {
    const { data } = await apiClient.get("/api/resource-library/netdisk-types");
    return data;
  },

  createResourceItem: async (payload: ResourceItemPayload): Promise<{ success: boolean; data: ResourceItem }> => {
    const { data } = await apiClient.post("/api/resource-library", payload);
    return data;
  },

  updateResourceItem: async (
    id: number,
    payload: ResourceItemPayload
  ): Promise<{ success: boolean; data: ResourceItem }> => {
    const { data } = await apiClient.put(`/api/resource-library/${id}`, payload);
    return data;
  },

  deleteResourceItem: async (id: number): Promise<{ success: boolean; message: string }> => {
    const { data } = await apiClient.delete(`/api/resource-library/${id}`);
    return data;
  },
};

// ── 知识库类型定义 ──────────────────────────────────────────────

export interface KnowledgeCollection {
  id: number;
  name: string;
  description: string;
  document_count: number;
  chunk_count: number;
  created_at: string;
}

export interface KnowledgeDocument {
  id: number;
  title: string;
  source_type: string;
  vector_doc_id?: string;
  chunk_count: number;
  status: string;
  error: string | null;
  source_job_id: string | null;
  created_at: string;
}

export interface VideoSearchResult {
  title: string;
  url: string;
  cover_url: string;
  platform: string;
  author: string;
  play_count: number;
  like_count: number;
  comment_count: number;
  share_count: number;
  duration: number;
  publish_time: string;
  heat_score: number;
  description: string;
}

export interface ResourceItem {
  id: number;
  name: string;
  netdiskType: string;
  url: string;
  feishuTableName: string;
  createdAt: string;
  updatedAt: string;
}

export type ResourceItemPayload = Omit<ResourceItem, "id"> & { id?: number };

export interface ResourceNetdiskType {
  name: string;
  count: number;
}

export interface ResourceListResponse {
  success: boolean;
  data: ResourceItem[];
  pagination: {
    page: number;
    pageSize: number;
    total: number;
    totalPages: number;
  };
}
