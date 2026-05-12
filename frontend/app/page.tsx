"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { taskApi, KnowledgeCollection } from "@/lib/tasks-api";
import VideoBackground from "@/components/video-background";
import { FullPipelineRequest, JobStatusResponse, JobStatus, STEP_LABELS, calculateProgress, getVisibleStepOrder } from "@/types/task";
import {
  STORAGE_KEY_API,
  STORAGE_KEY_SILICONFLOW_API_KEY,
  STORAGE_KEY_ZHIPU_API_KEY,
  STORAGE_KEY_SILICONFLOW_IMAGE_API_KEY,
  STORAGE_KEY_ZHIPU_IMAGE_API_KEY,
  STORAGE_KEY_WECHAT_APPID,
  STORAGE_KEY_WECHAT_SECRET,
  STORAGE_KEY_AI_PROVIDER,
  STORAGE_KEY_TEXT_MODEL,
  STORAGE_KEY_IMAGE_MODEL,
  STORAGE_KEY_SILICONFLOW_TEXT_MODEL,
  STORAGE_KEY_SILICONFLOW_IMAGE_MODEL,
  STORAGE_KEY_ZHIPU_TEXT_MODEL,
  STORAGE_KEY_ZHIPU_IMAGE_MODEL,
  STORAGE_KEY_IMAGE_PROVIDER,
  STORAGE_KEY_RAG_COLLECTION,
  STORAGE_KEY_RAG_TOP_K,
  STORAGE_KEY_RAG_EMBEDDING_MODEL,
  STORAGE_KEY_RAG_EMBEDDING_PROVIDER,
  STORAGE_KEY_RAG_EMBEDDING_API_KEY,
  readStoredRetrySettings,
} from "@/lib/task-settings";
import Navbar from "@/components/navbar";

// ── 步骤图标 ────────────────────────────────────────────────────────────────
const STEP_ICONS: Record<string, React.ReactNode> = {
  download: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  ),
  extract_audio: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 18V5l12-2v13" />
      <circle cx="6" cy="18" r="3" />
      <circle cx="18" cy="16" r="3" />
    </svg>
  ),
  transcribe: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" />
      <path d="M19 10v2a7 7 0 01-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  ),
  generate_article: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  ),
  generate_image: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <polyline points="21 15 16 10 5 21" />
    </svg>
  ),
  convert_html: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <polyline points="16 18 22 12 16 6" />
      <polyline points="8 6 2 12 8 18" />
    </svg>
  ),
  publish_draft: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  ),
};


function SettingsIcon(props: { className?: string }) {
  return (
    <svg className={props.className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M12 15a3 3 0 100-6 3 3 0 000 6z" />
      <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z" />
    </svg>
  );
}

function HistoryDeleteDialog(props: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  if (!props.open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={props.pending ? undefined : props.onCancel}
      />
      <div className="relative z-10 w-full max-w-md overflow-hidden rounded-3xl border border-white/15 bg-black/35 backdrop-blur-2xl shadow-2xl shadow-black/40">
        <div className="border-b border-white/10 px-6 py-5 text-left">
          <h3 className="text-lg font-bold text-white">{props.title}</h3>
          <p className="mt-2 text-sm leading-6 text-white/60">{props.description}</p>
        </div>
        <div className="flex items-center justify-end gap-3 px-6 py-5">
          <button
            type="button"
            onClick={props.onCancel}
            disabled={props.pending}
            className="inline-flex items-center rounded-full border border-white/15 bg-white/5 px-4 py-2 text-sm font-bold text-white/70 transition-all hover:border-white/25 hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            取消
          </button>
          <button
            type="button"
            onClick={props.onConfirm}
            disabled={props.pending}
            className="inline-flex items-center gap-2 rounded-full border border-red-300/25 bg-red-500/15 px-4 py-2 text-sm font-bold text-red-100 transition-all hover:border-red-300/45 hover:bg-red-500/25 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <svg className={`h-4 w-4 ${props.pending ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
            {props.pending ? "删除中" : props.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function RunningWarningDialog(props: {
  open: boolean;
  title: string;
  description: string;
  onClose: () => void;
}) {
  if (!props.open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={props.onClose}
      />
      <div className="relative z-10 w-full max-w-md overflow-hidden rounded-3xl border border-amber-300/20 bg-black/35 backdrop-blur-2xl shadow-2xl shadow-black/40">
        <div className="border-b border-amber-300/10 px-6 py-5 text-left">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-amber-400/30 bg-amber-500/15">
              <svg className="h-5 w-5 text-amber-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
              </svg>
            </div>
            <h3 className="text-lg font-bold text-white">{props.title}</h3>
          </div>
          <p className="mt-3 text-sm leading-6 text-white/60">{props.description}</p>
        </div>
        <div className="flex items-center justify-end px-6 py-5">
          <button
            type="button"
            onClick={props.onClose}
            className="inline-flex items-center rounded-full border border-white/15 bg-white/5 px-5 py-2 text-sm font-bold text-white/70 transition-all hover:border-white/25 hover:bg-white/10"
          >
            我知道了
          </button>
        </div>
      </div>
    </div>
  );
}

function PauseConfirmDialog(props: {
  open: boolean;
  currentStep: string | null;
  progress: number;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  if (!props.open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={props.pending ? undefined : props.onCancel}
      />
      <div className="relative z-10 w-full max-w-md overflow-hidden rounded-3xl border border-white/15 bg-black/35 backdrop-blur-2xl shadow-2xl shadow-black/40">
        <div className="flex items-center gap-3 border-b border-white/10 px-6 py-5 text-left">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-amber-500/15">
            <svg className="h-5 w-5 text-amber-400" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
              <rect x="6" y="4" width="4" height="16" rx="1" />
              <rect x="14" y="4" width="4" height="16" rx="1" />
            </svg>
          </div>
          <div>
            <h3 className="text-lg font-bold text-white">暂停当前任务？</h3>
            <p className="mt-1 text-sm leading-5 text-white/50">
              {props.currentStep
                ? `任务正在执行「${props.currentStep}」，当前进度 ${props.progress}%`
                : `当前进度 ${props.progress}%`}
            </p>
          </div>
        </div>
        <div className="px-6 py-4">
          <p className="text-sm leading-6 text-white/60">
            暂停后，当前步骤会完成然后停止执行后续步骤。你可以在历史任务中随时重新开始。
          </p>
        </div>
        <div className="flex items-center justify-end gap-3 border-t border-white/10 px-6 py-5">
          <button
            type="button"
            onClick={props.onCancel}
            disabled={props.pending}
            className="inline-flex items-center rounded-full border border-white/15 bg-white/5 px-4 py-2 text-sm font-bold text-white/70 transition-all hover:border-white/25 hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            继续执行
          </button>
          <button
            type="button"
            onClick={props.onConfirm}
            disabled={props.pending}
            className="inline-flex items-center gap-2 rounded-full border border-amber-300/25 bg-amber-500/15 px-4 py-2 text-sm font-bold text-amber-100 transition-all hover:border-amber-300/45 hover:bg-amber-500/25 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <svg className={`h-4 w-4 ${props.pending ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M10 9v6m4-6v6" />
            </svg>
            {props.pending ? "暂停中..." : "确认暂停"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Home() {
  const [url, setUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [wechatAppid, setWechatAppid] = useState("");
  const [wechatAppsecret, setWechatAppsecret] = useState("");
  const [aiProvider, setAiProvider] = useState<"siliconflow" | "zhipu">("siliconflow");
  const [textModel, setTextModel] = useState("");
  const [imageProvider, setImageProvider] = useState<"siliconflow" | "zhipu" | "">("");
  const [imageModel, setImageModel] = useState("");
  const [imageApiKey, setImageApiKey] = useState("");  // 图片服务商专用 API Key
  const [ragCollection, setRagCollection] = useState("");
  const [ragTopK, setRagTopK] = useState(5);
  const [ragEmbeddingModel, setRagEmbeddingModel] = useState("");
  const [ragEmbeddingProvider, setRagEmbeddingProvider] = useState<"siliconflow" | "zhipu">("zhipu");
  const [ragEmbeddingApiKey, setRagEmbeddingApiKey] = useState("");
  const [generateCoverImage, setGenerateCoverImage] = useState(true); // 封面生成开关，默认开启
  const [collections, setCollections] = useState<KnowledgeCollection[]>([]);
  const [showSettings, setShowSettings] = useState(false);
  const [loading, setLoading] = useState(false);
  const [historyActionError, setHistoryActionError] = useState("");
  const [historyAction, setHistoryAction] = useState<{
    jobId: string;
    type: "retry" | "delete" | "resume";
  } | null>(null);
  const [selectedJobIds, setSelectedJobIds] = useState<string[]>([]);
  const [deleteDialog, setDeleteDialog] = useState<{
    mode: "single" | "batch";
    jobIds: string[];
    title: string;
    description: string;
  } | null>(null);

  const [runningWarning, setRunningWarning] = useState<{
    title: string;
    description: string;
  } | null>(null);

  const [pauseDialogOpen, setPauseDialogOpen] = useState(false);
  const [pausing, setPausing] = useState(false);
  const [copiedJobId, setCopiedJobId] = useState<string | null>(null);

  // ─── 视频上传状态 ───────────────────────────────────────────
  const [publicIp, setPublicIp] = useState("");
  const [ipLoading, setIpLoading] = useState(false);
  const [ipCopied, setIpCopied] = useState(false);

  const handleQueryIp = async () => {
    setIpLoading(true);
    setPublicIp("");
    setIpCopied(false);
    try {
      const res = await fetch("https://myip.ipip.net");
      const text = await res.text();
      const match = text.match(/(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})/);
      setPublicIp(match ? match[1] : "查询失败，请重试");
    } catch {
      setPublicIp("查询失败，请重试");
    } finally {
      setIpLoading(false);
    }
  };

  const handleCopyIp = async () => {
    if (!publicIp || publicIp === "查询失败，请重试") return;
    try {
      await navigator.clipboard.writeText(publicIp);
      setIpCopied(true);
      setTimeout(() => setIpCopied(false), 2000);
    } catch {}
  };

  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState("");
  const [uploadedJobId, setUploadedJobId] = useState("");
  const [uploadedFileName, setUploadedFileName] = useState("");
  const uploadFileInputRef = useRef<HTMLInputElement>(null);
  const uploadAbortRef = useRef<AbortController | null>(null);
  const router = useRouter();

  // ─── 文案上传状态 ───────────────────────────────────────────
  const [textUploading, setTextUploading] = useState(false);
  const [textUploadProgress, setTextUploadProgress] = useState(0);
  const [textUploadError, setTextUploadError] = useState("");
  const [textUploadedJobId, setTextUploadedJobId] = useState("");
  const [textUploadedFileName, setTextUploadedFileName] = useState("");
  const textUploadFileInputRef = useRef<HTMLInputElement>(null);
  const textUploadAbortRef = useRef<AbortController | null>(null);

  const [activeJob, setActiveJob] = useState<JobStatusResponse | null>(null);
  const [historyJobs, setHistoryJobs] = useState<JobStatusResponse[]>([]);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const activeJobRef = useRef<JobStatusResponse | null>(null);

  // 同步更新 ref，确保 fetchHistory 始终拿到最新 activeJob
  useEffect(() => {
    activeJobRef.current = activeJob;
  }, [activeJob]);

  const fetchHistory = useCallback(async () => {
    try {
      const result = await taskApi.listJobs();
      const currentActiveJob = activeJobRef.current;
      // 如果当前有 activeJob（运行中），不把它放进历史列表，避免重复显示
      if (currentActiveJob && (currentActiveJob.status === JobStatus.RUNNING || currentActiveJob.status === JobStatus.PENDING)) {
        setHistoryJobs(result.jobs.filter((j) => j.job_id !== currentActiveJob.job_id));
      } else {
        setHistoryJobs(result.jobs);
      }
    } catch {}
  }, []);

  useEffect(() => {
    // 初始化 AI 服务商
    const storedProvider = localStorage.getItem(STORAGE_KEY_AI_PROVIDER);
    const currentProvider: "siliconflow" | "zhipu" = (storedProvider === "zhipu" || storedProvider === "siliconflow") ? storedProvider : "siliconflow";
    setAiProvider(currentProvider);

    // 根据当前服务商加载对应的 API Key
    if (currentProvider === "zhipu") {
      setApiKey(localStorage.getItem(STORAGE_KEY_ZHIPU_API_KEY) || localStorage.getItem(STORAGE_KEY_API) || "");
    } else {
      setApiKey(localStorage.getItem(STORAGE_KEY_SILICONFLOW_API_KEY) || localStorage.getItem(STORAGE_KEY_API) || "");
    }

    setWechatAppid(localStorage.getItem(STORAGE_KEY_WECHAT_APPID) || "");
    setWechatAppsecret(localStorage.getItem(STORAGE_KEY_WECHAT_SECRET) || "");

    // 图片服务商：优先读取独立配置，否则跟随主服务商
    const storedImgProvider = localStorage.getItem(STORAGE_KEY_IMAGE_PROVIDER);
    let effectiveImageProvider: "siliconflow" | "zhipu";
    if (storedImgProvider === "zhipu" || storedImgProvider === "siliconflow") {
      effectiveImageProvider = storedImgProvider;
      setImageProvider(storedImgProvider);
    } else {
      effectiveImageProvider = currentProvider;  // 默认跟随主服务商
      setImageProvider(currentProvider);
    }

    // 根据当前服务商加载对应的文本模型名称
    if (currentProvider === "zhipu") {
      setTextModel(localStorage.getItem(STORAGE_KEY_ZHIPU_TEXT_MODEL) || localStorage.getItem(STORAGE_KEY_TEXT_MODEL) || "");
    } else {
      setTextModel(localStorage.getItem(STORAGE_KEY_SILICONFLOW_TEXT_MODEL) || localStorage.getItem(STORAGE_KEY_TEXT_MODEL) || "");
    }

    // 根据图片服务商加载对应的图片模型名称（独立存储，不与文本服务商复用）
    if (effectiveImageProvider === "zhipu") {
      setImageModel(localStorage.getItem(STORAGE_KEY_ZHIPU_IMAGE_MODEL) || localStorage.getItem(STORAGE_KEY_IMAGE_MODEL) || "");
    } else {
      setImageModel(localStorage.getItem(STORAGE_KEY_SILICONFLOW_IMAGE_MODEL) || localStorage.getItem(STORAGE_KEY_IMAGE_MODEL) || "");
    }

    // 加载图片服务商专用 API Key（注意：读的是 IMAGE_API_KEY，不是主 API_KEY）
    if (effectiveImageProvider === "zhipu") {
      setImageApiKey(localStorage.getItem(STORAGE_KEY_ZHIPU_IMAGE_API_KEY) || "");
    } else {
      setImageApiKey(localStorage.getItem(STORAGE_KEY_SILICONFLOW_IMAGE_API_KEY) || "");
    }

    setRagCollection(localStorage.getItem(STORAGE_KEY_RAG_COLLECTION) || "");
    setRagTopK(parseInt(localStorage.getItem(STORAGE_KEY_RAG_TOP_K) || "5", 10));
    setRagEmbeddingModel(localStorage.getItem(STORAGE_KEY_RAG_EMBEDDING_MODEL) || "");
    const storedEmbProvider = localStorage.getItem(STORAGE_KEY_RAG_EMBEDDING_PROVIDER);
    if (storedEmbProvider === "zhipu" || storedEmbProvider === "siliconflow") {
      setRagEmbeddingProvider(storedEmbProvider);
    }
    setRagEmbeddingApiKey(localStorage.getItem(STORAGE_KEY_RAG_EMBEDDING_API_KEY) || "");

    // 获取历史任务，并自动恢复对正在运行任务的轮询
    taskApi.listJobs().then((result) => {
      // 检查是否有正在运行的任务，自动恢复轮询
      const runningJob = result.jobs.find(
        (job) => job.status === JobStatus.RUNNING || job.status === JobStatus.PENDING
      );
      if (runningJob) {
        setActiveJob(runningJob);
        startPolling(runningJob.job_id);
        // 正在运行的任务不放入历史列表，仅在主流程 UI 中展示
        setHistoryJobs(result.jobs.filter((j) => j.job_id !== runningJob.job_id));
      } else {
        // 没有运行中的任务：全部放入历史栏，不设置 activeJob
        setActiveJob(null);
        setHistoryJobs(result.jobs);
      }
    }).catch(() => {});

    // 获取知识库集合列表
    taskApi.listCollections().then((res) => {
      if (res.success) setCollections(res.data.collections);
    }).catch(() => {});
  }, []);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const pollOnce = useCallback(async (jobId: string): Promise<boolean> => {
    try {
      const job = await taskApi.getJobStatus(jobId);
      setActiveJob(job);
      setHistoryJobs((prev) =>
        prev.map((j) => (j.job_id === jobId ? job : j))
      );
      return job.status === JobStatus.SUCCESS || job.status === JobStatus.FAILED;
    } catch (error: unknown) {
      const err = error as { response?: { status?: number } };
      if (err.response?.status === 404) {
        setHistoryJobs((prev) => prev.filter((j) => j.job_id !== jobId));
        if (activeJobRef.current?.job_id === jobId) {
          setActiveJob(null);
        }
        stopPolling();
        return true;
      }
      return false;
    }
  }, [stopPolling]);

  const clearActiveJob = useCallback(() => {
    setActiveJob(null);
    setUploadedJobId("");
    setUploadedFileName("");
  }, []);

  const startPolling = useCallback((jobId: string) => {
    stopPolling();
    // 立即执行一次轮询，避免等待首个 interval
    pollOnce(jobId).then((done) => {
      if (done) {
        // 任务完成：刷新历史列表，并清除 activeJob 让任务回到历史栏
        fetchHistory().then(() => clearActiveJob());
        return;
      }
      pollingRef.current = setInterval(async () => {
        const isDone = await pollOnce(jobId);
        if (isDone) {
          stopPolling();
          fetchHistory().then(() => clearActiveJob());
        }
      }, 5000);
    });
  }, [stopPolling, fetchHistory, pollOnce, clearActiveJob]);

  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  // ─── 上传本地视频 ───────────────────────────────────────────
  const handleUploadVideo = async (file: File) => {
    const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
    const allowedExts = [".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv"];
    const allowedTypes = ["video/mp4", "video/quicktime", "video/x-msvideo", "video/x-matroska", "video/webm", "video/x-flv"];
    if (!allowedTypes.includes(file.type) && !allowedExts.includes(ext)) {
      setUploadError("不支持该格式，请上传 mp4 / mov / avi / mkv / webm 等视频文件");
      return;
    }
    if (file.size > 2 * 1024 * 1024 * 1024) {
      setUploadError("文件大小不能超过 2GB");
      return;
    }

    setUploading(true);
    setUploadProgress(0);
    setUploadError("");
    setUploadedJobId("");
    setUploadedFileName("");
    setActiveJob(null);

    const controller = new AbortController();
    uploadAbortRef.current = controller;

    try {
      const res = await taskApi.uploadVideo(
        file,
        !generateCoverImage,
        (pct) => setUploadProgress(pct),
        controller.signal,
      );
      if (res.success) {
        setUploadedJobId(res.job_id);
        setUploadedFileName(file.name);
      } else {
        setUploadError(res.message || "上传失败，请重试");
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "CanceledError") {
        setUploadError("已取消上传");
      } else {
        setUploadError(err instanceof Error ? err.message : "上传失败，请稍后重试");
      }
    } finally {
      setUploading(false);
      uploadAbortRef.current = null;
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    handleUploadVideo(file);
  };

  const handleCancelUpload = () => {
    uploadAbortRef.current?.abort();
  };

  // ─── 上传文案 ───────────────────────────────────────────
  const handleUploadText = async (file: File) => {
    const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
    const allowedExts = [".txt", ".pdf", ".md"];
    if (!allowedExts.includes(ext)) {
      setTextUploadError("不支持该格式，请上传 txt / pdf / md 等文案文件");
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      setTextUploadError("文件大小不能超过 50MB");
      return;
    }

    setTextUploading(true);
    setTextUploadProgress(0);
    setTextUploadError("");
    setTextUploadedJobId("");
    setTextUploadedFileName("");
    setActiveJob(null);

    const controller = new AbortController();
    textUploadAbortRef.current = controller;

    try {
      const res = await taskApi.uploadText(
        file,
        !generateCoverImage,
        (pct) => setTextUploadProgress(pct),
        controller.signal,
      );
      if (res.success) {
        setTextUploadedJobId(res.job_id);
        setTextUploadedFileName(file.name);
      } else {
        setTextUploadError(res.message || "上传失败，请重试");
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "CanceledError") {
        setTextUploadError("已取消上传");
      } else {
        setTextUploadError(err instanceof Error ? err.message : "上传失败，请稍后重试");
      }
    } finally {
      setTextUploading(false);
      textUploadAbortRef.current = null;
    }
  };

  const handleTextFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    handleUploadText(file);
  };

  const handleCancelTextUpload = () => {
    textUploadAbortRef.current?.abort();
  };

  // 切换 AI 服务商时，保存当前配置并加载新服务商的配置
  const handleAiProviderChange = (newProvider: "siliconflow" | "zhipu") => {
    // 1. 先保存当前服务商的所有配置到专用 localStorage（使用函数式 state 获取最新值）
    setApiKey((currentApiKey) => {
      if (aiProvider === "siliconflow") {
        localStorage.setItem(STORAGE_KEY_SILICONFLOW_API_KEY, currentApiKey);
      } else if (aiProvider === "zhipu") {
        localStorage.setItem(STORAGE_KEY_ZHIPU_API_KEY, currentApiKey);
      }
      return currentApiKey; // 不改变 state，仅用于保存
    });
    setTextModel((currentTextModel) => {
      if (aiProvider === "siliconflow") {
        localStorage.setItem(STORAGE_KEY_SILICONFLOW_TEXT_MODEL, currentTextModel);
      } else if (aiProvider === "zhipu") {
        localStorage.setItem(STORAGE_KEY_ZHIPU_TEXT_MODEL, currentTextModel);
      }
      return currentTextModel;
    });
    setImageModel((currentImageModel) => {
      if (aiProvider === "siliconflow") {
        localStorage.setItem(STORAGE_KEY_SILICONFLOW_IMAGE_MODEL, currentImageModel);
      } else if (aiProvider === "zhipu") {
        localStorage.setItem(STORAGE_KEY_ZHIPU_IMAGE_MODEL, currentImageModel);
      }
      return currentImageModel;
    });

    // 2. 切换服务商到 localStorage
    setAiProvider(newProvider);
    localStorage.setItem(STORAGE_KEY_AI_PROVIDER, newProvider);

    // 3. 从专用 localStorage 加载新服务商的配置（优先）并回退到通用 key
    if (newProvider === "siliconflow") {
      setApiKey(localStorage.getItem(STORAGE_KEY_SILICONFLOW_API_KEY) || localStorage.getItem(STORAGE_KEY_API) || "");
      setTextModel(localStorage.getItem(STORAGE_KEY_SILICONFLOW_TEXT_MODEL) || "");
      setImageModel(localStorage.getItem(STORAGE_KEY_SILICONFLOW_IMAGE_MODEL) || "");
    } else if (newProvider === "zhipu") {
      setApiKey(localStorage.getItem(STORAGE_KEY_ZHIPU_API_KEY) || localStorage.getItem(STORAGE_KEY_API) || "");
      setTextModel(localStorage.getItem(STORAGE_KEY_ZHIPU_TEXT_MODEL) || "");
      setImageModel(localStorage.getItem(STORAGE_KEY_ZHIPU_IMAGE_MODEL) || "");
    }
  };

  // 单独切换图片服务商（不影响文章生成的服务商）
  const handleImageProviderChange = (newProvider: "siliconflow" | "zhipu") => {
    // 保存当前图片服务商的配置
    if (imageProvider === "siliconflow") {
      localStorage.setItem(STORAGE_KEY_SILICONFLOW_IMAGE_MODEL, imageModel);
      localStorage.setItem(STORAGE_KEY_SILICONFLOW_IMAGE_API_KEY, imageApiKey);
    } else if (imageProvider === "zhipu") {
      localStorage.setItem(STORAGE_KEY_ZHIPU_IMAGE_MODEL, imageModel);
      localStorage.setItem(STORAGE_KEY_ZHIPU_IMAGE_API_KEY, imageApiKey);
    }

    // 切换图片服务商
    setImageProvider(newProvider);
    localStorage.setItem(STORAGE_KEY_IMAGE_PROVIDER, newProvider);

    // 加载新图片服务商的配置
    if (newProvider === "siliconflow") {
      setImageModel(localStorage.getItem(STORAGE_KEY_SILICONFLOW_IMAGE_MODEL) || "");
      setImageApiKey(localStorage.getItem(STORAGE_KEY_SILICONFLOW_IMAGE_API_KEY) || "");
    } else if (newProvider === "zhipu") {
      setImageModel(localStorage.getItem(STORAGE_KEY_ZHIPU_IMAGE_MODEL) || "");
      setImageApiKey(localStorage.getItem(STORAGE_KEY_ZHIPU_IMAGE_API_KEY) || "");
    }
  };

  // 获取图片服务商的 API Key（优先使用专用 imageApiKey，否则回退到图片服务商专用 Key）
  const getImageApiKey = useCallback((): string => {
    const provider = imageProvider || aiProvider;  // 图片服务商为空时跟随主服务商
    if (provider === "siliconflow") {
      return imageApiKey.trim() || localStorage.getItem(STORAGE_KEY_SILICONFLOW_IMAGE_API_KEY) || "";
    } else if (provider === "zhipu") {
      return imageApiKey.trim() || localStorage.getItem(STORAGE_KEY_ZHIPU_IMAGE_API_KEY) || "";
    }
    return apiKey.trim();
  }, [imageProvider, aiProvider, imageApiKey, apiKey]);

  const handleSubmit = async () => {
    // ── 上传文案分支：有 textUploadedJobId 则 resume ──
    if (textUploadedJobId && !url.trim() && !uploadedJobId) {
      const missing: string[] = [];
      if (!apiKey.trim()) missing.push("AI 服务 API Key");
      if (!wechatAppid.trim()) missing.push("微信小程序 AppID");
      if (!wechatAppsecret.trim()) missing.push("微信小程序 AppSecret");

      if (missing.length > 0) {
        setRunningWarning({ title: "配置不完整", description: `请先在配置中填写：${missing.join("、")}` });
        setShowSettings(true);
        return;
      }

      setLoading(true);
      setActiveJob(null);

      if (apiKey.trim()) {
        localStorage.setItem(STORAGE_KEY_API, apiKey.trim());
        // 同时保存到对应服务商的专用 key
        if (aiProvider === "siliconflow") {
          localStorage.setItem(STORAGE_KEY_SILICONFLOW_API_KEY, apiKey.trim());
        } else if (aiProvider === "zhipu") {
          localStorage.setItem(STORAGE_KEY_ZHIPU_API_KEY, apiKey.trim());
        }
      }
      if (wechatAppid.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_APPID, wechatAppid.trim());
      if (wechatAppsecret.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_SECRET, wechatAppsecret.trim());

      try {
        const res = await taskApi.resumeJob(textUploadedJobId, {
          api_key: apiKey.trim() || undefined,
          ai_provider: aiProvider,
          text_model: textModel.trim() || undefined,
          image_provider: imageProvider || undefined,
          image_api_key: getImageApiKey() || undefined,
          image_model: imageModel.trim() || undefined,
          wechat_appid: wechatAppid.trim() || undefined,
          wechat_appsecret: wechatAppsecret.trim() || undefined,
          skip_image_generation: !generateCoverImage,
        });

        if (res.success) {
          startPolling(textUploadedJobId);
          setTextUploadedJobId("");
          setTextUploadedFileName("");
          setUrl(textUploadedFileName ? `[已上传文案] ${textUploadedFileName}` : "");
        } else {
          setRunningWarning({ title: "启动处理失败", description: res.message || "请重试" });
        }
      } catch (error: unknown) {
        const err = error as { response?: { data?: { detail?: string } } };
        setRunningWarning({ title: "启动处理失败", description: err.response?.data?.detail || "请检查网络和参数" });
      } finally {
        setLoading(false);
      }
      return;
    }

    // ── 上传视频分支：有 uploadedJobId 则 resume ──
    if (uploadedJobId && !url.trim()) {
      const missing: string[] = [];
      if (!apiKey.trim()) missing.push("AI 服务 API Key");
      if (!wechatAppid.trim()) missing.push("微信小程序 AppID");
      if (!wechatAppsecret.trim()) missing.push("微信小程序 AppSecret");

      if (missing.length > 0) {
      setRunningWarning({ title: "配置不完整", description: `请先在配置中填写：${missing.join("、")}` });
      setShowSettings(true);
      return;
    }

    setLoading(true);
    setActiveJob(null);

    if (apiKey.trim()) {
      localStorage.setItem(STORAGE_KEY_API, apiKey.trim());
      // 同时保存到对应服务商的专用 key
      if (aiProvider === "siliconflow") {
        localStorage.setItem(STORAGE_KEY_SILICONFLOW_API_KEY, apiKey.trim());
      } else if (aiProvider === "zhipu") {
        localStorage.setItem(STORAGE_KEY_ZHIPU_API_KEY, apiKey.trim());
      }
    }
    if (wechatAppid.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_APPID, wechatAppid.trim());
    if (wechatAppsecret.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_SECRET, wechatAppsecret.trim());

      try {
        const res = await taskApi.resumeJob(uploadedJobId, {
          api_key: apiKey.trim() || undefined,
          ai_provider: aiProvider,
          text_model: textModel.trim() || undefined,
          image_provider: imageProvider || undefined,
          image_api_key: getImageApiKey() || undefined,
          image_model: imageModel.trim() || undefined,
          wechat_appid: wechatAppid.trim() || undefined,
          wechat_appsecret: wechatAppsecret.trim() || undefined,
          skip_image_generation: !generateCoverImage,
        });

        if (res.success) {
          startPolling(uploadedJobId);
          setUploadedJobId("");
          setUploadedFileName("");
          setUrl(uploadedFileName ? `[已上传] ${uploadedFileName}` : "");
        } else {
          setRunningWarning({ title: "启动处理失败", description: res.message || "请重试" });
        }
      } catch (error: unknown) {
        const err = error as { response?: { data?: { detail?: string } } };
        setRunningWarning({ title: "启动处理失败", description: err.response?.data?.detail || "请检查网络和参数" });
      } finally {
        setLoading(false);
      }
      return;
    }

    // ── 正常 URL 分支 ──
    if (!url.trim()) {
      setRunningWarning({ title: "提示", description: "请输入分享链接或上传本地视频或文案" });
      return;
    }

    const missing: string[] = [];
    if (!apiKey.trim()) missing.push("AI 服务 API Key");
    if (!wechatAppid.trim()) missing.push("微信小程序 AppID");
    if (!wechatAppsecret.trim()) missing.push("微信小程序 AppSecret");

    if (missing.length > 0) {
      setRunningWarning({ title: "配置不完整", description: `请先在配置中填写：${missing.join("、")}` });
      setShowSettings(true);
      return;
    }

    setLoading(true);
    setActiveJob(null);

    if (apiKey.trim()) {
      localStorage.setItem(STORAGE_KEY_API, apiKey.trim());
      // 同时保存到对应服务商的专用 key
      if (aiProvider === "siliconflow") {
        localStorage.setItem(STORAGE_KEY_SILICONFLOW_API_KEY, apiKey.trim());
      } else if (aiProvider === "zhipu") {
        localStorage.setItem(STORAGE_KEY_ZHIPU_API_KEY, apiKey.trim());
      }
    }
    if (wechatAppid.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_APPID, wechatAppid.trim());
    if (wechatAppsecret.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_SECRET, wechatAppsecret.trim());
    localStorage.setItem(STORAGE_KEY_AI_PROVIDER, aiProvider);
    localStorage.setItem(STORAGE_KEY_TEXT_MODEL, textModel.trim());
    localStorage.setItem(STORAGE_KEY_IMAGE_MODEL, imageModel.trim());
    if (aiProvider === "siliconflow") {
      localStorage.setItem(STORAGE_KEY_SILICONFLOW_TEXT_MODEL, textModel.trim());
    } else if (aiProvider === "zhipu") {
      localStorage.setItem(STORAGE_KEY_ZHIPU_TEXT_MODEL, textModel.trim());
    }
    const imgProvider = imageProvider || aiProvider;
    if (imgProvider === "siliconflow") {
      localStorage.setItem(STORAGE_KEY_SILICONFLOW_IMAGE_MODEL, imageModel.trim());
    } else if (imgProvider === "zhipu") {
      localStorage.setItem(STORAGE_KEY_ZHIPU_IMAGE_MODEL, imageModel.trim());
    }
    localStorage.setItem(STORAGE_KEY_RAG_COLLECTION, ragCollection);
    localStorage.setItem(STORAGE_KEY_RAG_TOP_K, String(ragTopK));
    localStorage.setItem(STORAGE_KEY_RAG_EMBEDDING_MODEL, ragEmbeddingModel.trim());
    localStorage.setItem(STORAGE_KEY_RAG_EMBEDDING_PROVIDER, ragEmbeddingProvider);
    localStorage.setItem(STORAGE_KEY_RAG_EMBEDDING_API_KEY, ragEmbeddingApiKey.trim());
    // 保存写作风格设置
    try {
      const req: FullPipelineRequest = {
        share_text: url.trim(),
        siliconflow_api_key: apiKey.trim(),
        ai_provider: aiProvider,
        wechat_appid: wechatAppid.trim() || undefined,
        wechat_appsecret: wechatAppsecret.trim() || undefined,
        text_model: textModel.trim() || undefined,
        image_provider: imageProvider || undefined,
        image_api_key: getImageApiKey() || undefined,
        image_model: imageModel.trim() || undefined,
        skip_image_generation: !generateCoverImage,
        rag_collection: ragCollection || undefined,
        rag_top_k: ragTopK,
        rag_embedding_model: ragEmbeddingModel.trim() || undefined,
        rag_embedding_provider: ragEmbeddingProvider,
        rag_embedding_api_key: ragEmbeddingApiKey.trim() || undefined,
      };

      const result = await taskApi.runFullPipeline(req);

      if (result.success && result.job_id) {
        startPolling(result.job_id);
      } else {
        setRunningWarning({ title: "任务提交失败", description: result.message || "请重试" });
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      setRunningWarning({ title: "任务提交失败", description: err.response?.data?.detail || "请检查网络和参数" });
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteHistoryJob = async (jobId: string) => {
    setHistoryActionError("");
    setHistoryAction({ jobId, type: "delete" });
    try {
      await taskApi.deleteJob(jobId);
      setSelectedJobIds((current) => current.filter((id) => id !== jobId));
      if (activeJob?.job_id === jobId) {
        setActiveJob(null);
        stopPolling();
      }
      await fetchHistory();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      setHistoryActionError(err.response?.data?.detail || "删除任务失败，请稍后重试");
    } finally {
      setHistoryAction(null);
    }
  };

  const handleToggleJobSelection = (jobId: string) => {
    setSelectedJobIds((current) =>
      current.includes(jobId)
        ? current.filter((id) => id !== jobId)
        : [...current, jobId]
    );
  };

  const handleToggleAllJobs = () => {
    setSelectedJobIds((current) =>
      current.length === historyJobs.length ? [] : historyJobs.map((job) => job.job_id)
    );
  };

  const openSingleDeleteDialog = (jobId: string) => {
    const job = historyJobs.find((j) => j.job_id === jobId);
    const isRunning = job && (job.status === JobStatus.RUNNING || job.status === JobStatus.PENDING);
    if (isRunning) {
      setRunningWarning({
        title: "无法删除运行中的任务",
        description: "该任务正在执行中，无法直接删除。请先暂停任务，等待任务停止后再进行删除操作。",
      });
      return;
    }
    setDeleteDialog({
      mode: "single",
      jobIds: [jobId],
      title: "删除这条任务？",
      description: "删除后将无法在历史记录中找回这条任务信息，请确认是否继续。",
    });
  };

  const openBatchDeleteDialog = () => {
    if (selectedJobIds.length === 0) return;

    const runningCount = historyJobs.filter(
      (j) => selectedJobIds.includes(j.job_id) && (j.status === JobStatus.RUNNING || j.status === JobStatus.PENDING)
    ).length;
    if (runningCount > 0) {
      setRunningWarning({
        title: "无法删除包含运行中的任务",
        description: `已选中的 ${selectedJobIds.length} 条任务中有 ${runningCount} 条正在执行中，无法直接删除。请先暂停这些任务，等待停止后再进行删除操作。`,
      });
      return;
    }

    setDeleteDialog({
      mode: "batch",
      jobIds: selectedJobIds,
      title: `删除已选中的 ${selectedJobIds.length} 条任务？`,
      description: "批量删除会同时移除这些历史任务记录，请确认这次操作。",
    });
  };

  const handleConfirmDelete = async () => {
    if (!deleteDialog) return;

    if (deleteDialog.mode === "single") {
      const [jobId] = deleteDialog.jobIds;
      await handleDeleteHistoryJob(jobId);
      setDeleteDialog(null);
      return;
    }

    setHistoryActionError("");
    setHistoryAction({ jobId: deleteDialog.jobIds.join(","), type: "delete" });
    try {
      await taskApi.batchDeleteJobs(deleteDialog.jobIds);
      if (activeJob && deleteDialog.jobIds.includes(activeJob.job_id)) {
        setActiveJob(null);
        stopPolling();
      }
      setSelectedJobIds([]);
      setDeleteDialog(null);
      await fetchHistory();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      setHistoryActionError(err.response?.data?.detail || "批量删除失败，请稍后重试");
    } finally {
      setHistoryAction(null);
    }
  };

  const handleRetryHistoryJob = async (jobId: string) => {
    setHistoryActionError("");
    setHistoryAction({ jobId, type: "retry" });
    // 重试前先保存当前配置到 localStorage，确保读到最新值
    if (apiKey.trim()) {
      localStorage.setItem(STORAGE_KEY_API, apiKey.trim());
      // 同时保存到对应服务商的专用 key
      if (aiProvider === "siliconflow") {
        localStorage.setItem(STORAGE_KEY_SILICONFLOW_API_KEY, apiKey.trim());
      } else if (aiProvider === "zhipu") {
        localStorage.setItem(STORAGE_KEY_ZHIPU_API_KEY, apiKey.trim());
      }
    }
    if (wechatAppid.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_APPID, wechatAppid.trim());
    if (wechatAppsecret.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_SECRET, wechatAppsecret.trim());
    localStorage.setItem(STORAGE_KEY_AI_PROVIDER, aiProvider);
    localStorage.setItem(STORAGE_KEY_TEXT_MODEL, textModel.trim());
    localStorage.setItem(STORAGE_KEY_IMAGE_PROVIDER, imageProvider);
    localStorage.setItem(STORAGE_KEY_IMAGE_MODEL, imageModel.trim());
    if (imageProvider === "siliconflow") {
      localStorage.setItem(STORAGE_KEY_SILICONFLOW_IMAGE_API_KEY, imageApiKey.trim());
    } else if (imageProvider === "zhipu") {
      localStorage.setItem(STORAGE_KEY_ZHIPU_IMAGE_API_KEY, imageApiKey.trim());
    }
    if (aiProvider === "siliconflow") {
      localStorage.setItem(STORAGE_KEY_SILICONFLOW_TEXT_MODEL, textModel.trim());
    } else if (aiProvider === "zhipu") {
      localStorage.setItem(STORAGE_KEY_ZHIPU_TEXT_MODEL, textModel.trim());
    }
    const imgProvider1 = imageProvider || aiProvider;
    if (imgProvider1 === "siliconflow") {
      localStorage.setItem(STORAGE_KEY_SILICONFLOW_IMAGE_MODEL, imageModel.trim());
    } else if (imgProvider1 === "zhipu") {
      localStorage.setItem(STORAGE_KEY_ZHIPU_IMAGE_MODEL, imageModel.trim());
    }
    // 保存图片 API Key 到专用 storage
    if (imageProvider === "siliconflow") {
      localStorage.setItem(STORAGE_KEY_SILICONFLOW_IMAGE_API_KEY, imageApiKey.trim());
    } else if (imageProvider === "zhipu") {
      localStorage.setItem(STORAGE_KEY_ZHIPU_IMAGE_API_KEY, imageApiKey.trim());
    }
    // 保存 RAG 配置
    if (ragCollection.trim()) localStorage.setItem(STORAGE_KEY_RAG_COLLECTION, ragCollection.trim());
    if (ragEmbeddingModel.trim()) localStorage.setItem(STORAGE_KEY_RAG_EMBEDDING_MODEL, ragEmbeddingModel.trim());
    if (ragEmbeddingProvider.trim()) localStorage.setItem(STORAGE_KEY_RAG_EMBEDDING_PROVIDER, ragEmbeddingProvider.trim());
    if (ragEmbeddingApiKey.trim()) localStorage.setItem(STORAGE_KEY_RAG_EMBEDDING_API_KEY, ragEmbeddingApiKey.trim());
    try {
      const settings = readStoredRetrySettings();
      await taskApi.retryFailedJob(jobId, {
        api_key: settings.apiKey || undefined,
        ai_provider: settings.aiProvider,
        text_model: settings.textModel || undefined,
        image_provider: settings.imageProvider || undefined,
        image_api_key: settings.imageApiKey || undefined,
        image_model: settings.imageModel || undefined,
        wechat_appid: settings.wechatAppid || undefined,
        wechat_appsecret: settings.wechatAppsecret || undefined,
        rag_collection: settings.ragCollection || undefined,
        rag_embedding_model: settings.ragEmbeddingModel || undefined,
        rag_embedding_provider: settings.ragEmbeddingProvider || undefined,
        rag_embedding_api_key: settings.ragEmbeddingApiKey || undefined,
      });
      startPolling(jobId);
      await fetchHistory();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      setHistoryActionError(err.response?.data?.detail || "重试任务失败，请检查配置后再试");
    } finally {
      setHistoryAction(null);
    }
  };

  const handleRegenerateHistoryJob = async (jobId: string) => {
    setHistoryActionError("");
    setHistoryAction({ jobId, type: "retry" });
    // 再次生成前先保存当前配置到 localStorage
    if (apiKey.trim()) {
      localStorage.setItem(STORAGE_KEY_API, apiKey.trim());
      if (aiProvider === "siliconflow") {
        localStorage.setItem(STORAGE_KEY_SILICONFLOW_API_KEY, apiKey.trim());
      } else if (aiProvider === "zhipu") {
        localStorage.setItem(STORAGE_KEY_ZHIPU_API_KEY, apiKey.trim());
      }
    }
    if (wechatAppid.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_APPID, wechatAppid.trim());
    if (wechatAppsecret.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_SECRET, wechatAppsecret.trim());
    localStorage.setItem(STORAGE_KEY_AI_PROVIDER, aiProvider);
    localStorage.setItem(STORAGE_KEY_TEXT_MODEL, textModel.trim());
    localStorage.setItem(STORAGE_KEY_IMAGE_MODEL, imageModel.trim());
    localStorage.setItem(STORAGE_KEY_IMAGE_PROVIDER, imageProvider);

    if (imageProvider === "siliconflow") {
      localStorage.setItem(STORAGE_KEY_SILICONFLOW_IMAGE_API_KEY, imageApiKey.trim());
    } else if (imageProvider === "zhipu") {
      localStorage.setItem(STORAGE_KEY_ZHIPU_IMAGE_API_KEY, imageApiKey.trim());
    }

    if (aiProvider === "siliconflow") {
      localStorage.setItem(STORAGE_KEY_SILICONFLOW_TEXT_MODEL, textModel.trim());
    } else if (aiProvider === "zhipu") {
      localStorage.setItem(STORAGE_KEY_ZHIPU_TEXT_MODEL, textModel.trim());
    }
    const imgProvider2 = imageProvider || aiProvider;
    if (imgProvider2 === "siliconflow") {
      localStorage.setItem(STORAGE_KEY_SILICONFLOW_IMAGE_MODEL, imageModel.trim());
    } else if (imgProvider2 === "zhipu") {
      localStorage.setItem(STORAGE_KEY_ZHIPU_IMAGE_MODEL, imageModel.trim());
    }
    localStorage.setItem(STORAGE_KEY_RAG_COLLECTION, ragCollection);
    localStorage.setItem(STORAGE_KEY_RAG_TOP_K, String(ragTopK));
    localStorage.setItem(STORAGE_KEY_RAG_EMBEDDING_MODEL, ragEmbeddingModel.trim());
    localStorage.setItem(STORAGE_KEY_RAG_EMBEDDING_PROVIDER, ragEmbeddingProvider);
    localStorage.setItem(STORAGE_KEY_RAG_EMBEDDING_API_KEY, ragEmbeddingApiKey.trim());
    try {
      const settings = readStoredRetrySettings();
      const res = await taskApi.regenerateJob(jobId, {
        api_key: settings.apiKey || apiKey.trim(),
        ai_provider: aiProvider,
        text_model: textModel.trim() || undefined,
        image_provider: imageProvider || undefined,
        image_api_key: settings.imageApiKey || imageApiKey.trim() || undefined,
        image_model: imageModel.trim() || undefined,
        skip_image_generation: !generateCoverImage,
        wechat_appid: wechatAppid.trim() || undefined,
        wechat_appsecret: wechatAppsecret.trim() || undefined,
        rag_collection: ragCollection || undefined,
        rag_top_k: ragTopK,
        rag_embedding_model: ragEmbeddingModel.trim() || undefined,
        rag_embedding_provider: ragEmbeddingProvider,
        rag_embedding_api_key: ragEmbeddingApiKey.trim() || undefined,
      });
      if (res.success && res.job_id) {
        startPolling(res.job_id);
      } else {
        setHistoryActionError(res.message || "再次生成失败，请检查配置");
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      setHistoryActionError(err.response?.data?.detail || "再次生成失败，请检查配置");
    } finally {
      setHistoryAction(null);
    }
  };

  const handleCopyJobId = async (jobId: string) => {
    try {
      await navigator.clipboard.writeText(jobId);
      setCopiedJobId(jobId);
      setTimeout(() => setCopiedJobId(null), 2000);
    } catch {}
  };

  const handlePauseJob = async () => {
    if (!activeJob) return;
    setPausing(true);
    try {
      await taskApi.pauseJob(activeJob.job_id);
      stopPolling();
      // 刷新一次状态以获取最新的 PAUSED 数据
      try {
        const updated = await taskApi.getJobStatus(activeJob.job_id);
        setActiveJob(updated);
        activeJobRef.current = updated; // 同步更新 ref，确保 fetchHistory 拿到最新值
      } catch {}
      await fetchHistory();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      setRunningWarning({ title: "暂停任务失败", description: err.response?.data?.detail || "请稍后重试" });
    } finally {
      setPausing(false);
      setPauseDialogOpen(false);
    }
  };

  const handlePauseHistoryJob = async (jobId: string) => {
    try {
      await taskApi.pauseJob(jobId);
      if (activeJob?.job_id === jobId) {
        stopPolling();
        try {
          const updated = await taskApi.getJobStatus(jobId);
          setActiveJob(updated);
          activeJobRef.current = updated; // 同步更新 ref
        } catch {}
      }
      // 立即刷新历史列表中该任务的状态
      setHistoryJobs((prev) =>
        prev.map((j) => (j.job_id === jobId ? { ...j, status: JobStatus.PAUSED } : j))
      );
      await fetchHistory();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      setRunningWarning({ title: "暂停任务失败", description: err.response?.data?.detail || "请稍后重试" });
    }
  };

  const handleResumeHistoryJob = async (jobId: string) => {
    setHistoryActionError("");
    setHistoryAction({ jobId, type: "resume" });
    // 继续前先保存当前配置到 localStorage，确保读到最新值
    if (apiKey.trim()) {
      localStorage.setItem(STORAGE_KEY_API, apiKey.trim());
      // 同时保存到对应服务商的专用 key
      if (aiProvider === "siliconflow") {
        localStorage.setItem(STORAGE_KEY_SILICONFLOW_API_KEY, apiKey.trim());
      } else if (aiProvider === "zhipu") {
        localStorage.setItem(STORAGE_KEY_ZHIPU_API_KEY, apiKey.trim());
      }
    }
    if (wechatAppid.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_APPID, wechatAppid.trim());
    if (wechatAppsecret.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_SECRET, wechatAppsecret.trim());
    localStorage.setItem(STORAGE_KEY_AI_PROVIDER, aiProvider);
    localStorage.setItem(STORAGE_KEY_TEXT_MODEL, textModel.trim());
    localStorage.setItem(STORAGE_KEY_IMAGE_MODEL, imageModel.trim());
    if (aiProvider === "siliconflow") {
      localStorage.setItem(STORAGE_KEY_SILICONFLOW_TEXT_MODEL, textModel.trim());
    } else if (aiProvider === "zhipu") {
      localStorage.setItem(STORAGE_KEY_ZHIPU_TEXT_MODEL, textModel.trim());
    }
    const imgProvider3 = imageProvider || aiProvider;
    if (imgProvider3 === "siliconflow") {
      localStorage.setItem(STORAGE_KEY_SILICONFLOW_IMAGE_MODEL, imageModel.trim());
    } else if (imgProvider3 === "zhipu") {
      localStorage.setItem(STORAGE_KEY_ZHIPU_IMAGE_MODEL, imageModel.trim());
    }
    if (imageProvider === "siliconflow") {
      localStorage.setItem(STORAGE_KEY_SILICONFLOW_IMAGE_API_KEY, imageApiKey.trim());
    } else if (imageProvider === "zhipu") {
      localStorage.setItem(STORAGE_KEY_ZHIPU_IMAGE_API_KEY, imageApiKey.trim());
    }
    try {
      const settings = readStoredRetrySettings();
      await taskApi.resumeJob(jobId, {
        api_key: settings.apiKey || undefined,
        ai_provider: settings.aiProvider,
        text_model: settings.textModel || undefined,
        image_provider: imageProvider || undefined,
        image_api_key: settings.imageApiKey || undefined,
        image_model: settings.imageModel || undefined,
        wechat_appid: settings.wechatAppid || undefined,
        wechat_appsecret: settings.wechatAppsecret || undefined,
        skip_image_generation: !generateCoverImage,
      });
      // 立即刷新 activeJob，确保活动卡片立刻从"已暂停"切换到"运行中"
      try {
        const updated = await taskApi.getJobStatus(jobId);
        setActiveJob(updated);
        activeJobRef.current = updated; // 同步更新 ref
      } catch {}
      // 立即刷新历史列表中该任务的状态
      setHistoryJobs((prev) =>
        prev.map((j) => (j.job_id === jobId ? { ...j, status: JobStatus.RUNNING } : j))
      );
      startPolling(jobId);
      await fetchHistory();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      setHistoryActionError(err.response?.data?.detail || "继续任务失败，请检查配置后再试");
    } finally {
      setHistoryAction(null);
    }
  };

  const progress = activeJob ? calculateProgress(activeJob) : 0;
  const activeStepOrder = activeJob ? getVisibleStepOrder(activeJob) : [];
  const currentStepLabel = activeJob?.current_step
    ? STEP_LABELS[activeJob.current_step] || activeJob.current_step
    : null;

  const isJobRunning = activeJob && (activeJob.status === JobStatus.RUNNING || activeJob.status === JobStatus.PENDING);
  const isJobPaused = activeJob && activeJob.status === JobStatus.PAUSED;
  const isJobDone = activeJob && activeJob.status === JobStatus.SUCCESS;
  const isJobFailed = activeJob && activeJob.status === JobStatus.FAILED;
  const isAllHistorySelected = historyJobs.length > 0 && selectedJobIds.length === historyJobs.length;
  const isBatchDeleting = historyAction?.type === "delete" && historyAction.jobId.includes(",");

  return (
    <div className="min-h-screen text-white">
      <HistoryDeleteDialog
        open={deleteDialog !== null}
        title={deleteDialog?.title || ""}
        description={deleteDialog?.description || ""}
        confirmLabel={deleteDialog?.mode === "batch" ? "确认批量删除" : "确认删除"}
        pending={historyAction?.type === "delete"}
        onCancel={() => {
          if (!historyAction || historyAction.type !== "delete") {
            setDeleteDialog(null);
          }
        }}
        onConfirm={handleConfirmDelete}
      />
      <RunningWarningDialog
        open={runningWarning !== null}
        title={runningWarning?.title || ""}
        description={runningWarning?.description || ""}
        onClose={() => setRunningWarning(null)}
      />
      <PauseConfirmDialog
        open={pauseDialogOpen}
        currentStep={currentStepLabel}
        progress={progress}
        pending={pausing}
        onCancel={() => setPauseDialogOpen(false)}
        onConfirm={handlePauseJob}
      />
      <Navbar />

      <main className="relative flex flex-col items-center overflow-hidden px-4 pb-16 pt-28 sm:px-6 sm:pt-32 lg:px-8">
        <VideoBackground />
        <div className="relative z-10 flex w-full max-w-5xl flex-col items-center text-center">
          <div className="pill-badge mb-8 shadow-sm">
            <span className="h-2 w-2 shrink-0 rounded-full bg-[#D94E28]" aria-hidden />
            <span>自动化工作流:短视频转文章一站完成</span>
          </div>

          <h1 className="hero-headline mb-10 max-w-4xl">短视频转换平台</h1>

          <div className="mb-4 w-full max-w-2xl space-y-3">
            <div className="floating-input">
              <div className="shrink-0 text-gray-400">
                <svg className="h-6 w-6" fill="currentColor" viewBox="0 0 24 24" aria-hidden>
                  <path d="M8 5v14l11-7z" />
                </svg>
              </div>
              <input
                id="hero-url"
                type="text"
                placeholder="粘贴抖音分享链接…"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
                className="min-w-0 flex-1 border-none bg-transparent text-base font-medium text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-0"
              />
              <button
                type="button"
                onClick={handleSubmit}
                disabled={loading || (!url && !uploadedJobId && !textUploadedJobId)}
                className="btn-brand-inner disabled:pointer-events-none disabled:opacity-50"
              >
                {loading ? "提交中…" : "免费生成"}
              </button>
              <button
                type="button"
                onClick={() => setShowSettings(!showSettings)}
                className={`flex shrink-0 items-center gap-1.5 rounded-full border px-4 py-2.5 text-sm font-bold transition-all backdrop-blur-sm ${
                  showSettings
                    ? "border-[#D94E28]/60 bg-[#D94E28]/15 text-[#FF8A65]"
                    : "border-white/20 bg-white/10 text-white/70 hover:border-white/35 hover:bg-white/15 hover:text-white/90"
                }`}
              >
                <SettingsIcon className="h-4 w-4" />
                配置
              </button>
            </div>

            {/* 分隔线 */}
            <div className="flex items-center gap-3">
              <div className="flex-1 h-px bg-white/15" />
              <span className="text-xs text-white/35 shrink-0">或直接上传</span>
              <div className="flex-1 h-px bg-white/15" />
            </div>

            {/* 隐藏文件输入 */}
            <input
              ref={uploadFileInputRef}
              type="file"
              accept="video/mp4,video/quicktime,video/x-msvideo,video/x-matroska,video/webm,.mp4,.mov,.avi,.mkv,.webm,.flv,.wmv"
              className="hidden"
              onChange={handleFileChange}
            />
            <input
              ref={textUploadFileInputRef}
              type="file"
              accept=".txt,.pdf,.md"
              className="hidden"
              onChange={handleTextFileChange}
            />

            {/* 两个上传按钮并排，各占一半 */}
            <div className="flex gap-3">
              {/* 左侧：上传视频 */}
              <div className="flex-1 overflow-hidden rounded-xl border border-dashed border-white/20 bg-white/5 backdrop-blur-sm">
                {!uploading && !uploadedJobId ? (
                  <button
                    type="button"
                    onClick={() => uploadFileInputRef.current?.click()}
                    className="group w-full flex items-center justify-center gap-2 px-4 py-3.5 text-sm text-white/50 hover:text-white/85 transition-all duration-200"
                  >
                    <svg className="w-4 h-4 shrink-0 text-[#D94E28] group-hover:scale-110 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                    </svg>
                    <span className="truncate">上传视频</span>
                  </button>
                ) : uploading ? (
                  <div className="px-4 py-4 space-y-2">
                    <div className="flex items-center justify-between text-xs text-white/55">
                      <span>视频上传中…</span>
                      <span>{uploadProgress}%</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-white/15 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-[#D94E28] to-[#FF8A65] transition-all duration-200"
                        style={{ width: `${uploadProgress}%` }}
                      />
                    </div>
                    <button
                      type="button"
                      onClick={handleCancelUpload}
                      className="text-xs text-white/30 hover:text-red-300 transition-colors"
                    >
                      取消
                    </button>
                  </div>
                ) : uploadedJobId ? (
                  <div className="flex items-center gap-2 px-4 py-3.5">
                    <svg className="w-4 h-4 text-emerald-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                    <span className="text-sm text-emerald-300 truncate">视频: {uploadedFileName}</span>
                  </div>
                ) : null}

                {uploadError && (
                  <div className="flex items-center justify-between gap-2 px-4 pb-3.5 text-xs text-red-300">
                    <span className="truncate">{uploadError}</span>
                    <button
                      type="button"
                      onClick={() => setUploadError("")}
                      className="text-white/30 hover:text-white/60 transition-colors shrink-0"
                    >
                      ✕
                    </button>
                  </div>
                )}
              </div>

              {/* 右侧：上传文案 */}
              <div className="flex-1 overflow-hidden rounded-xl border border-dashed border-white/20 bg-white/5 backdrop-blur-sm">
                {!textUploading && !textUploadedJobId ? (
                  <button
                    type="button"
                    onClick={() => textUploadFileInputRef.current?.click()}
                    className="group w-full flex items-center justify-center gap-2 px-4 py-3.5 text-sm text-white/50 hover:text-white/85 transition-all duration-200"
                  >
                    <svg className="w-4 h-4 shrink-0 text-[#D94E28] group-hover:scale-110 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    <span className="truncate">上传文案</span>
                  </button>
                ) : textUploading ? (
                  <div className="px-4 py-4 space-y-2">
                    <div className="flex items-center justify-between text-xs text-white/55">
                      <span>文案上传中…</span>
                      <span>{textUploadProgress}%</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-white/15 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-[#D94E28] to-[#FF8A65] transition-all duration-200"
                        style={{ width: `${textUploadProgress}%` }}
                      />
                    </div>
                    <button
                      type="button"
                      onClick={handleCancelTextUpload}
                      className="text-xs text-white/30 hover:text-red-300 transition-colors"
                    >
                      取消
                    </button>
                  </div>
                ) : textUploadedJobId ? (
                  <div className="flex items-center gap-2 px-4 py-3.5">
                    <svg className="w-4 h-4 text-emerald-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                    <span className="text-sm text-emerald-300 truncate">文案: {textUploadedFileName}</span>
                  </div>
                ) : null}

                {textUploadError && (
                  <div className="flex items-center justify-between gap-2 px-4 pb-3.5 text-xs text-red-300">
                    <span className="truncate">{textUploadError}</span>
                    <button
                      type="button"
                      onClick={() => setTextUploadError("")}
                      className="text-white/30 hover:text-white/60 transition-colors shrink-0"
                    >
                      ✕
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>

                    {showSettings && (
            <div className="mb-8 w-full max-w-2xl overflow-hidden rounded-2xl border border-white/15 bg-black/20 backdrop-blur-xl shadow-lg shadow-black/10">
              <div className="border-b border-white/10 px-6 py-3">
                <h3 className="text-sm font-bold text-white/80">高级设置</h3>
              </div>
              <div className="p-6 space-y-5">

                {/* ═══ 必填配置 ══════════════════════════════════════════ */}
                <div className="rounded-xl border border-[#D94E28]/20 bg-[#D94E28]/5 p-4">
                  <div className="flex items-center gap-2 mb-4">
                    <span className="flex h-5 w-5 items-center justify-center rounded bg-[#D94E28] text-[10px] font-bold text-white">!</span>
                    <span className="text-xs font-bold uppercase tracking-wider text-[#FF8A65]">必填配置</span>
                  </div>
                  <div className="space-y-4">
                    {/* AI 服务商 + API Key 同行 */}
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-5">
                      <div className="sm:col-span-2">
                        <label className="mb-1.5 block text-xs font-bold uppercase tracking-wider text-white/50">
                          AI 服务商
                        </label>
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={() => handleAiProviderChange("siliconflow")}
                            className={`flex-1 rounded-lg border px-3 py-2 text-xs font-medium transition-all ${
                              aiProvider === "siliconflow"
                                ? "border-[#D94E28] bg-[#D94E28]/20 text-white"
                                : "border-white/15 bg-white/10 text-white/60 hover:bg-white/15"
                            }`}
                          >
                            SF
                          </button>
                          <button
                            type="button"
                            onClick={() => handleAiProviderChange("zhipu")}
                            className={`flex-1 rounded-lg border px-3 py-2 text-xs font-medium transition-all ${
                              aiProvider === "zhipu"
                                ? "border-[#D94E28] bg-[#D94E28]/20 text-white"
                                : "border-white/15 bg-white/10 text-white/60 hover:bg-white/15"
                            }`}
                          >
                            智谱
                          </button>
                        </div>
                      </div>
                      <div className="sm:col-span-3">
                        <label className="mb-1.5 block text-xs font-bold uppercase tracking-wider text-white/50">
                          {aiProvider === "zhipu" ? "智谱 API Key" : "SiliconFlow API Key"}
                        </label>
                        <input
                          type="password"
                          placeholder={aiProvider === "zhipu" ? "从智谱 AI 开放平台获取" : "sk-..."}
                          value={apiKey}
                          onChange={(e) => setApiKey(e.target.value)}
                          className="w-full rounded-xl border border-white/15 bg-white/10 px-4 py-2.5 text-sm text-white placeholder:text-white/30 focus:border-[#D94E28]/50 focus:outline-none focus:bg-white/15 transition-colors"
                        />
                      </div>
                    </div>

                    {/* 微信配置同行 */}
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <div>
                        <label className="mb-1.5 block text-xs font-bold uppercase tracking-wider text-white/50">
                          微信 AppID
                        </label>
                        <input
                          type="text"
                          placeholder="wx..."
                          value={wechatAppid}
                          onChange={(e) => setWechatAppid(e.target.value)}
                          className="w-full rounded-xl border border-white/15 bg-white/10 px-4 py-2.5 text-sm text-white placeholder:text-white/30 focus:border-[#D94E28]/50 focus:outline-none focus:bg-white/15 transition-colors"
                        />
                      </div>
                      <div>
                        <label className="mb-1.5 block text-xs font-bold uppercase tracking-wider text-white/50">
                          微信 AppSecret
                        </label>
                        <input
                          type="password"
                          placeholder="..."
                          value={wechatAppsecret}
                          onChange={(e) => setWechatAppsecret(e.target.value)}
                          className="w-full rounded-xl border border-white/15 bg-white/10 px-4 py-2.5 text-sm text-white placeholder:text-white/30 focus:border-[#D94E28]/50 focus:outline-none focus:bg-white/15 transition-colors"
                        />
                      </div>
                    </div>
                  </div>
                </div>

                {/* ═══ 模型配置 ══════════════════════════════════════════ */}
                <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                  <div className="flex items-center gap-2 mb-4">
                    <svg className="h-4 w-4 text-white/40" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                    </svg>
                    <span className="text-xs font-bold uppercase tracking-wider text-white/50">模型配置</span>
                  </div>

                  {/* 文章生成 */}
                  <div className="mb-4 pb-4 border-b border-white/10">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-[10px] font-bold text-[#FF8A65] bg-[#FF8A65]/10 px-1.5 py-0.5 rounded">文</span>
                      <span className="text-xs text-white/60">文章生成模型</span>
                    </div>
                    <input
                      type="text"
                      placeholder={aiProvider === "zhipu" ? "glm-4-flash（默认）" : "Qwen/Qwen3-14B（默认）"}
                      value={textModel}
                      onChange={(e) => setTextModel(e.target.value)}
                      className="w-full rounded-lg border border-white/15 bg-white/5 px-4 py-2.5 text-sm text-white placeholder:text-white/30 focus:border-[#D94E28]/50 focus:outline-none focus:bg-white/10 transition-colors"
                    />
                  </div>

                  {/* 图片生成 */}
                  <div>
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] font-bold text-[#FF8A65] bg-[#FF8A65]/10 px-1.5 py-0.5 rounded">图</span>
                        <span className="text-xs text-white/60">图片生成</span>
                      </div>
                      {/* 封面生成开关 */}
                      <button
                        type="button"
                        onClick={() => setGenerateCoverImage((v) => !v)}
                        className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-all ${
                          generateCoverImage
                            ? "border-[#D94E28]/50 bg-[#D94E28]/15 text-[#FF8A65]"
                            : "border-white/15 bg-white/5 text-white/35 line-through"
                        }`}
                      >
                        <span className={`h-1.5 w-1.5 rounded-full transition-colors ${generateCoverImage ? "bg-[#D94E28]" : "bg-white/30"}`} />
                        {generateCoverImage ? "生成封面" : "不生成封面"}
                      </button>
                    </div>
                    <div className={`space-y-3 transition-opacity duration-200 ${generateCoverImage ? "opacity-100" : "opacity-35 pointer-events-none"}`}>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => handleImageProviderChange("siliconflow")}
                          className={`flex-1 rounded-lg border px-3 py-2 text-xs font-medium transition-all ${
                            imageProvider === "siliconflow"
                              ? "border-[#D94E28] bg-[#D94E28]/20 text-white"
                              : "border-white/15 bg-white/10 text-white/60 hover:bg-white/15"
                          }`}
                        >
                          SiliconFlow
                        </button>
                        <button
                          type="button"
                          onClick={() => handleImageProviderChange("zhipu")}
                          className={`flex-1 rounded-lg border px-3 py-2 text-xs font-medium transition-all ${
                            imageProvider === "zhipu"
                              ? "border-[#D94E28] bg-[#D94E28]/20 text-white"
                              : "border-white/15 bg-white/10 text-white/60 hover:bg-white/15"
                          }`}
                        >
                          智谱 AI
                        </button>
                      </div>
                      <div>
                        <label className="mb-1.5 block text-xs text-white/40">
                          {imageProvider === "zhipu" ? "智谱图片 API Key" : "SiliconFlow 图片 API Key"}
                        </label>
                        <input
                          type="password"
                          placeholder={imageProvider === "zhipu" ? "留空则使用主 API Key" : "留空则使用主 API Key"}
                          value={imageApiKey}
                          onChange={(e) => setImageApiKey(e.target.value)}
                          className="w-full rounded-lg border border-white/15 bg-white/5 px-4 py-2.5 text-sm text-white placeholder:text-white/30 focus:border-[#D94E28]/50 focus:outline-none focus:bg-white/10 transition-colors"
                        />
                      </div>
                      <input
                        type="text"
                        placeholder={imageProvider === "zhipu" ? "cogview-3（默认）" : imageProvider === "siliconflow" ? "FLUX.1-schnell（默认）" : "自动跟随主服务商"}
                        value={imageModel}
                        onChange={(e) => setImageModel(e.target.value)}
                        className="w-full rounded-lg border border-white/15 bg-white/5 px-4 py-2.5 text-sm text-white placeholder:text-white/30 focus:border-[#D94E28]/50 focus:outline-none focus:bg-white/10 transition-colors"
                      />
                    </div>
                  </div>
                </div>

                {/* ═══ 工具 ════════════════════════════════════════════ */}
                <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <svg className="h-4 w-4 text-white/40" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                        <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      </svg>
                      <span className="text-xs font-bold uppercase tracking-wider text-white/50">工具</span>
                    </div>
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs text-white/40">
                      公网 IP（用于微信公众号 IP 白名单配置）
                    </label>
                    <div className="flex items-center gap-2 flex-wrap">
                      <button
                        type="button"
                        onClick={handleQueryIp}
                        disabled={ipLoading}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/10 px-3 py-2 text-xs font-medium text-white/70 transition-all hover:border-white/25 hover:bg-white/15 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <svg className={`h-3.5 w-3.5 ${ipLoading ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <circle cx="12" cy="12" r="10" />
                          <path strokeLinecap="round" d="M2 12h4m12 0h4M12 2v4m0 12v4" />
                        </svg>
                        {ipLoading ? "查询中..." : "查询"}
                      </button>
                      {publicIp && (
                        <>
                          <span className="rounded-lg border border-white/15 bg-white/10 px-3 py-2 text-xs font-mono text-white/80">
                            {publicIp}
                          </span>
                          <button
                            type="button"
                            onClick={handleCopyIp}
                            title="复制 IP"
                            className="inline-flex items-center gap-1 rounded-lg border border-white/15 bg-white/10 px-2 py-2 text-xs text-white/70 transition-all hover:border-white/25 hover:bg-white/15"
                          >
                            {ipCopied ? (
                              <svg className="h-3.5 w-3.5 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <polyline points="20 6 9 17 4 12" />
                              </svg>
                            ) : (
                              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                                <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
                              </svg>
                            )}
                          </button>
                          <a
                            href="https://developers.weixin.qq.com/console/product/mp/wxfd4b3edcc57e114d?tab1=basicInfo&tab2=dev"
                            target="_blank"
                            rel="noopener noreferrer"
                            title="前往微信公众平台"
                            className="inline-flex items-center gap-1 rounded-lg border border-[#D94E28]/40 bg-[#D94E28]/15 px-2 py-2 text-xs text-[#FF8A65] transition-all hover:border-[#D94E28]/60 hover:bg-[#D94E28]/25"
                          >
                            <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
                              <polyline points="15 3 21 3 21 9" />
                              <line x1="10" y1="14" x2="21" y2="3" />
                            </svg>
                          </a>
                        </>
                      )}
                    </div>
                  </div>
                </div>

                {/* ═══ RAG 知识库增强 ══════════════════════════════════════════ */}
                <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <svg className="h-4 w-4 text-white/40" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                      </svg>
                      <span className="text-xs font-bold uppercase tracking-wider text-white/50">RAG 知识库增强</span>
                    </div>
                    <a
                      href="/knowledge"
                      className="text-[11px] text-[#FF8A65] hover:text-[#D94E28] transition-colors"
                    >
                      管理知识库 →
                    </a>
                  </div>

                  <div className="space-y-4">
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <div>
                        <label className="mb-1.5 block text-xs text-white/40">知识库集合</label>
                        <select
                          value={ragCollection}
                          onChange={(e) => setRagCollection(e.target.value)}
                          className="w-full rounded-lg border border-white/15 bg-white/10 px-4 py-2.5 text-sm text-white focus:border-[#D94E28]/50 focus:outline-none appearance-none cursor-pointer"
                        >
                          <option value="" className="bg-gray-800">不使用 RAG</option>
                          {collections.map((c) => (
                            <option key={c.id} value={c.name} className="bg-gray-800">
                              {c.name} ({c.document_count} 文档)
                            </option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="mb-1.5 block text-xs text-white/40">
                          检索数量 (Top K): <span className="text-white/70">{ragTopK}</span>
                        </label>
                        <input
                          type="range"
                          min={1}
                          max={10}
                          value={ragTopK}
                          onChange={(e) => setRagTopK(parseInt(e.target.value, 10))}
                          className="w-full accent-[#D94E28]"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <div>
                        <label className="mb-1.5 block text-xs text-white/40">向量模型服务商</label>
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={() => setRagEmbeddingProvider("siliconflow")}
                            className={`flex-1 rounded-lg border px-3 py-2 text-xs font-medium transition-all ${
                              ragEmbeddingProvider === "siliconflow"
                                ? "border-[#D94E28] bg-[#D94E28]/20 text-white"
                                : "border-white/15 bg-white/10 text-white/60 hover:bg-white/15"
                            }`}
                          >
                            SiliconFlow
                          </button>
                          <button
                            type="button"
                            onClick={() => setRagEmbeddingProvider("zhipu")}
                            className={`flex-1 rounded-lg border px-3 py-2 text-xs font-medium transition-all ${
                              ragEmbeddingProvider === "zhipu"
                                ? "border-[#D94E28] bg-[#D94E28]/20 text-white"
                                : "border-white/15 bg-white/10 text-white/60 hover:bg-white/15"
                            }`}
                          >
                            智谱 AI
                          </button>
                        </div>
                      </div>
                      <div>
                        <label className="mb-1.5 block text-xs text-white/40">
                          向量模型 (Embedding)
                        </label>
                        <input
                          type="text"
                          placeholder={ragEmbeddingProvider === "zhipu" ? "embedding-3（默认）" : "Qwen/Qwen3-Embedding-8B（默认）"}
                          value={ragEmbeddingModel}
                          onChange={(e) => setRagEmbeddingModel(e.target.value)}
                          className="w-full rounded-lg border border-white/15 bg-white/5 px-4 py-2.5 text-sm text-white placeholder:text-white/30 focus:border-[#D94E28]/50 focus:outline-none focus:bg-white/10 transition-colors"
                        />
                      </div>
                    </div>

                    <div>
                      <label className="mb-1.5 block text-xs text-white/40">
                        向量模型 API Key <span className="text-white/25">（留空则使用上方 AI 服务商的 Key）</span>
                      </label>
                      <input
                        type="password"
                        placeholder={ragEmbeddingProvider === "zhipu" ? "智谱 API Key" : "SiliconFlow API Key"}
                        value={ragEmbeddingApiKey}
                        onChange={(e) => setRagEmbeddingApiKey(e.target.value)}
                        className="w-full rounded-lg border border-white/15 bg-white/5 px-4 py-2.5 text-sm text-white placeholder:text-white/30 focus:border-[#D94E28]/50 focus:outline-none focus:bg-white/10 transition-colors"
                      />
                    </div>
                  </div>

                  <p className="mt-4 text-[11px] text-white/25 leading-relaxed">
                    启用后，文章生成时会从知识库检索相关背景知识注入 prompt，提升文章质量和专业度
                  </p>
                </div>

              </div>
            </div>
          )}
{activeJob && (
            <div className="mb-6 w-full max-w-2xl overflow-hidden rounded-2xl border border-white/15 bg-black/20 backdrop-blur-xl shadow-lg">
              <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
                <div className="flex items-center gap-3">
                  <span className={`h-2.5 w-2.5 rounded-full ${
                    isJobPaused ? "bg-amber-400" :
                    isJobRunning ? "bg-blue-400 animate-pulse" :
                    isJobDone ? "bg-green-400" :
                    "bg-red-400"
                  }`} />
                  <span className="text-sm font-bold text-white/80">
                    {isJobDone ? "处理完成" : isJobFailed ? "处理失败" : isJobPaused ? `已暂停 — ${currentStepLabel || "已停止"}` : `正在处理 — ${currentStepLabel || "准备中"}`}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  {isJobRunning && (
                    <button
                      type="button"
                      onClick={() => setPauseDialogOpen(true)}
                      className="inline-flex items-center gap-1.5 rounded-full border border-amber-300/25 bg-amber-500/10 px-3 py-1.5 text-xs font-bold text-amber-100 transition-all hover:border-amber-300/45 hover:bg-amber-500/20"
                    >
                      <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                        <rect x="6" y="4" width="4" height="16" rx="1" />
                        <rect x="14" y="4" width="4" height="16" rx="1" />
                      </svg>
                      暂停
                    </button>
                  )}
                </div>
              </div>
                {/* ── 步骤流程图 ─────────────────────────────────────────── */}
                <div className="px-5 py-5">
                  <div className="flex items-start justify-between">
                  {activeStepOrder.map((stepName, idx) => {
                    const stepResult = activeJob.steps.find((s) => s.step === stepName);
                    const isActive = activeJob.current_step === stepName;
                    let stepStatus: "pending" | "running" | "success" | "failed" = "pending";
                    if (stepResult) {
                      if (stepResult.status === JobStatus.SUCCESS) stepStatus = "success";
                      else if (stepResult.status === JobStatus.FAILED) stepStatus = "failed";
                      else if (stepResult.status === JobStatus.RUNNING || isActive) stepStatus = "running";
                    }
                    const isLast = idx === activeStepOrder.length - 1;

                    const circleBase = "relative z-10 flex h-9 w-9 sm:h-10 sm:w-10 shrink-0 items-center justify-center rounded-full transition-all duration-300";
                    const circleStyle = {
                      pending: "bg-white/5 border border-white/15 text-white/25",
                      running: "bg-[#D94E28]/15 border-2 border-[#D94E28] text-[#FF8A65] shadow-lg shadow-[#D94E28]/20",
                      success: "bg-emerald-500/15 border border-emerald-400/40 text-emerald-400",
                      failed: "bg-red-500/15 border border-red-400/40 text-red-400",
                    };
                    const lineStyle = {
                      pending: "bg-white/10",
                      running: "bg-gradient-to-r from-[#D94E28] to-white/10",
                      success: "bg-emerald-500/50",
                      failed: "bg-red-500/40",
                    };

                    return (
                      <div key={stepName} className="flex flex-1 items-start">
                        <div className="flex flex-col items-center gap-1.5 sm:gap-2">
                          {/* 圆圈 + 图标 */}
                          <div className={`${circleBase} ${circleStyle[stepStatus]} ${stepStatus === "running" ? "animate-pulse" : ""}`}>
                            {stepStatus === "success" ? (
                              <svg className="h-4 w-4 sm:h-5 sm:w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
                                <polyline points="20 6 9 17 4 12" />
                              </svg>
                            ) : stepStatus === "failed" ? (
                              <svg className="h-4 w-4 sm:h-5 sm:w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
                                <line x1="18" y1="6" x2="6" y2="18" />
                                <line x1="6" y1="6" x2="18" y2="18" />
                              </svg>
                            ) : (
                              <div className="h-4 w-4 sm:h-5 sm:w-5">{STEP_ICONS[stepName]}</div>
                            )}
                            {/* 运行中光圈 */}
                            {stepStatus === "running" && (
                              <span className="absolute inset-0 rounded-full border-2 border-[#D94E28] animate-ping opacity-30" />
                            )}
                          </div>
                          {/* 标签 */}
                          <span className={`hidden sm:block text-[11px] font-bold leading-tight text-center ${
                            stepStatus === "running" ? "text-[#FF8A65]" :
                            stepStatus === "success" ? "text-emerald-400" :
                            stepStatus === "failed" ? "text-red-400" :
                            "text-white/30"
                          }`}>
                            {STEP_LABELS[stepName]}
                          </span>
                        </div>
                        {/* 连接线 */}
                        {!isLast && (
                          <div className="flex-1 flex items-center pt-4 sm:pt-5 px-0.5">
                            <div className={`h-0.5 w-full rounded-full transition-all duration-500 ${
                              lineStyle[stepStatus]
                            }`} />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
              {isJobFailed && activeJob.error && (
                <div className="border-t border-white/10 px-5 py-3 text-left text-sm text-red-400">
                  {activeJob.error}
                </div>
              )}
              {isJobDone && (
                <div className="border-t border-white/10 px-5 py-3 flex items-center justify-between">
                  <span className="text-sm text-green-400 font-bold">🎉 任务处理完成</span>
                  <button
                    type="button"
                    onClick={() => {
                      fetchHistory();
                      clearActiveJob();
                    }}
                    className="inline-flex items-center gap-1.5 rounded-full border border-green-300/25 bg-green-500/15 px-3 py-1.5 text-xs font-bold text-green-100 transition-all hover:border-green-300/45 hover:bg-green-500/25"
                  >
                    <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                    完成
                  </button>
                </div>
              )}
            </div>
          )}

          <div className="app-window-chrome mt-2 w-full max-w-6xl overflow-hidden">
            <div className="flex h-11 items-center justify-between border-b border-white/10 bg-white/5 backdrop-blur-sm px-4">
              <div className="flex gap-2">
                <span className="h-3 w-3 rounded-full bg-[#FF5F57]" />
                <span className="h-3 w-3 rounded-full bg-[#FEBC2E]" />
                <span className="h-3 w-3 rounded-full bg-[#28C840]" />
              </div>
              <button
                type="button"
                onClick={fetchHistory}
                className="inline-flex items-center gap-1.5 rounded-full bg-[#D94E28]/80 backdrop-blur-sm px-3 py-1.5 text-xs font-bold text-white shadow-sm hover:bg-[#D94E28] transition-colors"
              >
                刷新
              </button>
            </div>
            <div className="min-h-[340px] bg-black/10 backdrop-blur-sm p-6">
              {historyJobs.length === 0 ? (
                <div className="flex h-full flex-col items-center justify-center py-12 text-center">
                  <div className="mb-4 text-4xl">...</div>
                  <p className="text-sm font-bold text-white/40">暂无历史任务</p>
                  <p className="mt-1 text-xs text-white/25">提交链接后，完成的任务会显示在这里</p>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="mb-4 flex flex-col gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        onClick={handleToggleAllJobs}
                        className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-bold transition-all ${
                          isAllHistorySelected
                            ? "border-[#FF8A65]/45 bg-[#D94E28]/15 text-[#FFD3C6]"
                            : "border-white/15 bg-white/5 text-white/65 hover:border-white/25 hover:bg-white/10"
                        }`}
                      >
                        <span
                          className={`flex h-4 w-4 items-center justify-center rounded-full border transition-all ${
                            isAllHistorySelected
                              ? "border-[#FF8A65]/70 bg-[#D94E28] text-white"
                              : "border-white/25 bg-transparent text-transparent"
                          }`}
                        >
                          <svg className="h-2.5 w-2.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.4">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M3.5 8.5L6.5 11.5L12.5 4.5" />
                          </svg>
                        </span>
                        {isAllHistorySelected ? "取消全选" : "一键勾选全部"}
                      </button>
                      <div>
                        <h3 className="text-sm font-bold text-white/70">历史任务</h3>
                        <p className="text-xs text-white/35">共 {historyJobs.length} 条，已选 {selectedJobIds.length} 条</p>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={openBatchDeleteDialog}
                      disabled={selectedJobIds.length === 0 || isBatchDeleting}
                      className="inline-flex items-center justify-center gap-2 rounded-full border border-red-300/20 bg-red-500/10 px-4 py-2 text-xs font-bold text-red-100 transition-all hover:border-red-300/40 hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-45"
                    >
                      <svg className={`h-3.5 w-3.5 ${isBatchDeleting ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                      {isBatchDeleting ? "删除中..." : "批量删除"}
                    </button>
                  </div>
                  {historyActionError && (
                    <div className="rounded-xl border border-red-400/20 bg-red-500/10 px-4 py-3 text-left text-sm text-red-200">
                      {historyActionError}
                    </div>
                  )}
                    {historyJobs.map((job) => {
                      const jobProgress = calculateProgress(job);
                      const historyStepOrder = getVisibleStepOrder(job);
                      const completedCount = job.steps.filter((s) => s.status === JobStatus.SUCCESS).length;
                    const failedStep = job.steps.find((s) => s.status === JobStatus.FAILED);
                    const articleStep = job.steps.find((s) => s.step === "generate_article");
                    const jobTitle = articleStep?.data?.title || `任务 #${job.job_id.slice(0, 8)}`;
                    const isSelected = selectedJobIds.includes(job.job_id);
                    const isRetryingJob = historyAction?.jobId === job.job_id && historyAction.type === "retry";
                    const isDeletingJob = historyAction?.jobId === job.job_id && historyAction.type === "delete";
                    const isActing = isRetryingJob || isDeletingJob;
                    const canRetry = job.status === JobStatus.FAILED;
                    const canResume = job.status === JobStatus.PAUSED;
                    const canPause = job.status === JobStatus.RUNNING || job.status === JobStatus.PENDING;
                    const canRegenerate = job.status === JobStatus.SUCCESS && !!job.transcript_path;

                    return (
                      <div
                        key={job.job_id}
                        className="group rounded-xl border border-white/10 bg-white/5 backdrop-blur-sm p-4 transition-all hover:border-white/20 hover:bg-white/10"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex min-w-0 flex-1 items-start gap-3">
                            <button
                              type="button"
                              onClick={() => handleToggleJobSelection(job.job_id)}
                              className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border transition-all ${
                                isSelected
                                  ? "border-[#FF8A65]/70 bg-[#D94E28] text-white"
                                  : "border-white/20 bg-white/5 text-transparent hover:border-white/35 hover:bg-white/10"
                              }`}
                              aria-label={`选择任务 ${jobTitle}`}
                            >
                              <svg className="h-3 w-3" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.4">
                                <path strokeLinecap="round" strokeLinejoin="round" d="M3.5 8.5L6.5 11.5L12.5 4.5" />
                              </svg>
                            </button>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span className={`h-2 w-2 shrink-0 rounded-full ${
                                  job.status === JobStatus.SUCCESS ? "bg-green-400" :
                                  job.status === JobStatus.FAILED ? "bg-red-400" :
                                  job.status === JobStatus.RUNNING ? "bg-blue-400 animate-pulse" :
                                  job.status === JobStatus.PAUSED ? "bg-amber-400" :
                                  "bg-yellow-400"
                                }`} />
                                <p className="truncate text-sm font-bold text-white/85">{jobTitle}</p>
                                <button
                                  type="button"
                                  onClick={() => handleCopyJobId(job.job_id)}
                                  title={`复制任务 ID: ${job.job_id}`}
                                  className="inline-flex shrink-0 items-center gap-1 rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] font-mono text-white/40 transition-all hover:border-white/25 hover:bg-white/10 hover:text-white/70"
                                >
                                  {copiedJobId === job.job_id ? (
                                    <svg className="h-3 w-3 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                      <polyline points="20 6 9 17 4 12" />
                                    </svg>
                                  ) : (
                                    <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                                      <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
                                    </svg>
                                  )}
                                  <span>{job.job_id.slice(0, 8)}</span>
                                </button>
                              </div>
                              {failedStep && (
                                <p className="mt-1 text-xs text-red-400">
                                  失败步骤：{STEP_LABELS[failedStep.step] || failedStep.step}
                                </p>
                              )}
                            </div>
                          </div>
                          <div className="flex shrink-0 items-center gap-3">
                            <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
                              job.status === JobStatus.SUCCESS ? "bg-green-500/20 text-green-300" :
                              job.status === JobStatus.FAILED ? "bg-red-500/20 text-red-300" :
                              job.status === JobStatus.RUNNING ? "bg-blue-500/20 text-blue-300" :
                              job.status === JobStatus.PAUSED ? "bg-amber-500/20 text-amber-300" :
                              "bg-yellow-500/20 text-yellow-300"
                            }`}>
                              {job.status === JobStatus.SUCCESS ? "完成" :
                               job.status === JobStatus.FAILED ? "失败" :
                               job.status === JobStatus.RUNNING ? "进行中" :
                               job.status === JobStatus.PAUSED ? "已暂停" :
                               "等待中"}
                            </span>
                            <span className="text-[10px] text-white/35">
                              {new Date(job.created_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                            </span>
                          </div>
                        </div>
                        <div className="mt-2 flex items-center gap-3">
                          <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/10">
                            <div
                              className={`h-full rounded-full transition-all ${
                                job.status === JobStatus.FAILED ? "bg-red-400/60" :
                                job.status === JobStatus.SUCCESS ? "bg-green-400" :
                                job.status === JobStatus.PAUSED ? "bg-amber-400/60" :
                                "bg-[#D94E28]"
                              }`}
                              style={{ width: `${jobProgress}%` }}
                            />
                          </div>
                            <span className="shrink-0 text-[10px] font-bold text-white/35">
                              {completedCount}/{historyStepOrder.length}
                            </span>
                        </div>
                        <div className="mt-3 flex items-center justify-between gap-3 border-t border-white/10 pt-3">
                          <div className="text-left text-[11px] text-white/35">
                            {failedStep
                              ? `失败步骤：${STEP_LABELS[failedStep.step] || failedStep.step}`
                              : "可在这里继续管理任务"}
                          </div>
                          <div className="flex items-center gap-2">
                            {canPause && (
                              <button
                                type="button"
                                onClick={() => handlePauseHistoryJob(job.job_id)}
                                className="inline-flex items-center gap-1.5 rounded-full border border-amber-300/25 bg-amber-500/15 px-3 py-1.5 text-[11px] font-bold text-amber-100 transition-all hover:border-amber-300/45 hover:bg-amber-500/25"
                              >
                                <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                                  <rect x="6" y="4" width="4" height="16" rx="1" />
                                  <rect x="14" y="4" width="4" height="16" rx="1" />
                                </svg>
                                暂停
                              </button>
                            )}
                            {canResume && (
                              <button
                                type="button"
                                onClick={() => handleResumeHistoryJob(job.job_id)}
                                disabled={isActing}
                                className="inline-flex items-center gap-1.5 rounded-full border border-emerald-300/25 bg-emerald-500/15 px-3 py-1.5 text-[11px] font-bold text-emerald-100 transition-all hover:border-emerald-300/45 hover:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                <svg className={`h-3.5 w-3.5 ${isRetryingJob ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                                  <path d="M8 5v14l11-7z" />
                                </svg>
                                {isRetryingJob ? "提交中..." : "继续"}
                              </button>
                            )}
                            {canRetry && (
                              <button
                                type="button"
                                onClick={() => handleRetryHistoryJob(job.job_id)}
                                disabled={isActing}
                                className="inline-flex items-center gap-1.5 rounded-full border border-[#FF8A65]/30 bg-[#D94E28]/15 px-3 py-1.5 text-[11px] font-bold text-[#FFD3C6] transition-all hover:border-[#FF8A65]/60 hover:bg-[#D94E28]/25 disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                <svg className={`h-3.5 w-3.5 ${isRetryingJob ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.3">
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 12a8 8 0 018-8V2.83a1 1 0 011.707-.707l3.293 3.293a1 1 0 010 1.414l-3.293 3.293A1 1 0 0112 9.17V8a4 4 0 00-4 4H4z" />
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M20 12a8 8 0 01-8 8v1.17a1 1 0 01-.707.707l-3.293-3.293a1 1 0 010-1.414l3.293-3.293A1 1 0 0012 14.83V16a4 4 0 004-4h4z" />
                                </svg>
                                {isRetryingJob ? "提交中..." : "重试"}
                              </button>
                            )}
                            {canRegenerate && (
                              <button
                                type="button"
                                onClick={() => handleRegenerateHistoryJob(job.job_id)}
                                disabled={isActing}
                                className="inline-flex items-center gap-1.5 rounded-full border border-blue-300/25 bg-blue-500/15 px-3 py-1.5 text-[11px] font-bold text-blue-100 transition-all hover:border-blue-300/45 hover:bg-blue-500/25 disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                <svg className={`h-3.5 w-3.5 ${isRetryingJob ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                                </svg>
                                {isRetryingJob ? "提交中..." : "再次生成"}
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => openSingleDeleteDialog(job.job_id)}
                              disabled={isActing}
                              className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-[11px] font-bold text-white/70 transition-all hover:border-red-300/40 hover:bg-red-500/10 hover:text-red-200 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                              </svg>
                              {isDeletingJob ? "删除中..." : "删除"}
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
