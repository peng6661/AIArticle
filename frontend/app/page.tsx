"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { taskApi, KnowledgeCollection } from "@/lib/tasks-api";
import { FullPipelineRequest, JobStatusResponse, JobStatus, STEP_LABELS, calculateProgress, getVisibleStepOrder } from "@/types/task";
import {
  STORAGE_KEY_API,
  STORAGE_KEY_WECHAT_APPID,
  STORAGE_KEY_WECHAT_SECRET,
  STORAGE_KEY_INLINE_IMAGES,
  STORAGE_KEY_AI_PROVIDER,
  STORAGE_KEY_TEXT_MODEL,
  STORAGE_KEY_IMAGE_MODEL,
  STORAGE_KEY_RAG_COLLECTION,
  STORAGE_KEY_RAG_TOP_K,
  STORAGE_KEY_RAG_EMBEDDING_MODEL,
  STORAGE_KEY_RAG_EMBEDDING_PROVIDER,
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

function VideoBackground() {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const playPromise = video.play();
    if (playPromise !== undefined) {
      playPromise.catch(() => {
        video.muted = true;
        video.play().catch(() => {});
      });
    }
  }, []);

  return (
    <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
      <video
        ref={videoRef}
        autoPlay
        loop
        muted
        playsInline
        poster="/homeScreen01.webm"
        className="h-full w-full object-cover"
      >
        <source src="/homeScreen01.webm" type="video/webm" />
      </video>
      <div className="absolute inset-0 bg-black/30" />
    </div>
  );
}

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
  const [generateInlineImages, setGenerateInlineImages] = useState(false);
  const [aiProvider, setAiProvider] = useState<"siliconflow" | "zhipu">("siliconflow");
  const [textModel, setTextModel] = useState("");
  const [imageModel, setImageModel] = useState("");
  const [ragCollection, setRagCollection] = useState("");
  const [ragTopK, setRagTopK] = useState(5);
  const [ragEmbeddingModel, setRagEmbeddingModel] = useState("");
  const [ragEmbeddingProvider, setRagEmbeddingProvider] = useState<"siliconflow" | "zhipu">("zhipu");
  const [collections, setCollections] = useState<KnowledgeCollection[]>([]);
  const [showSettings, setShowSettings] = useState(false);
  const [loading, setLoading] = useState(false);
  const [historyActionError, setHistoryActionError] = useState("");
  const [historyAction, setHistoryAction] = useState<{
    jobId: string;
    type: "retry" | "delete";
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

  const [activeJob, setActiveJob] = useState<JobStatusResponse | null>(null);
  const [historyJobs, setHistoryJobs] = useState<JobStatusResponse[]>([]);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchHistory = useCallback(async () => {
    try {
      const result = await taskApi.listJobs();
      setHistoryJobs(result.jobs);
    } catch {}
  }, []);

  useEffect(() => {
    setApiKey(localStorage.getItem(STORAGE_KEY_API) || "");
    setWechatAppid(localStorage.getItem(STORAGE_KEY_WECHAT_APPID) || "");
    setWechatAppsecret(localStorage.getItem(STORAGE_KEY_WECHAT_SECRET) || "");
    setGenerateInlineImages(
      localStorage.getItem(STORAGE_KEY_INLINE_IMAGES) === "true"
    );
    const storedProvider = localStorage.getItem(STORAGE_KEY_AI_PROVIDER);
    if (storedProvider === "zhipu" || storedProvider === "siliconflow") {
      setAiProvider(storedProvider);
    }
    setTextModel(localStorage.getItem(STORAGE_KEY_TEXT_MODEL) || "");
    setImageModel(localStorage.getItem(STORAGE_KEY_IMAGE_MODEL) || "");
    setRagCollection(localStorage.getItem(STORAGE_KEY_RAG_COLLECTION) || "");
    setRagTopK(parseInt(localStorage.getItem(STORAGE_KEY_RAG_TOP_K) || "5", 10));
    setRagEmbeddingModel(localStorage.getItem(STORAGE_KEY_RAG_EMBEDDING_MODEL) || "");
    const storedEmbProvider = localStorage.getItem(STORAGE_KEY_RAG_EMBEDDING_PROVIDER);
    if (storedEmbProvider === "zhipu" || storedEmbProvider === "siliconflow") {
      setRagEmbeddingProvider(storedEmbProvider);
    }
    fetchHistory();
    // 获取知识库集合列表
    taskApi.listCollections().then((res) => {
      if (res.success) setCollections(res.data.collections);
    }).catch(() => {});
  }, [fetchHistory]);

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
    } catch {
      return false;
    }
  }, []);

  const startPolling = useCallback((jobId: string) => {
    stopPolling();
    // 立即执行一次轮询，避免等待首个 interval
    pollOnce(jobId).then((done) => {
      if (done) {
        fetchHistory();
        return;
      }
      let consecutiveErrors = 0;
      pollingRef.current = setInterval(async () => {
        try {
          const isDone = await pollOnce(jobId);
          consecutiveErrors = 0;
          if (isDone) {
            stopPolling();
            fetchHistory();
          }
        } catch {
          consecutiveErrors += 1;
          if (consecutiveErrors >= 5) {
            stopPolling();
          }
        }
      }, 5000);
    });
  }, [stopPolling, fetchHistory, pollOnce]);

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

  const handleSubmit = async () => {
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

    if (apiKey.trim()) localStorage.setItem(STORAGE_KEY_API, apiKey.trim());
    if (wechatAppid.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_APPID, wechatAppid.trim());
    if (wechatAppsecret.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_SECRET, wechatAppsecret.trim());
    localStorage.setItem(STORAGE_KEY_INLINE_IMAGES, String(generateInlineImages));

      try {
        const res = await taskApi.resumeJob(uploadedJobId, {
          api_key: apiKey.trim() || undefined,
          ai_provider: aiProvider,
          text_model: textModel.trim() || undefined,
          image_model: imageModel.trim() || undefined,
          wechat_appid: wechatAppid.trim() || undefined,
          wechat_appsecret: wechatAppsecret.trim() || undefined,
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
      setRunningWarning({ title: "提示", description: "请输入分享链接或上传本地视频" });
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

    if (apiKey.trim()) localStorage.setItem(STORAGE_KEY_API, apiKey.trim());
    if (wechatAppid.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_APPID, wechatAppid.trim());
    if (wechatAppsecret.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_SECRET, wechatAppsecret.trim());
    localStorage.setItem(STORAGE_KEY_INLINE_IMAGES, String(generateInlineImages));
    localStorage.setItem(STORAGE_KEY_AI_PROVIDER, aiProvider);
    localStorage.setItem(STORAGE_KEY_TEXT_MODEL, textModel.trim());
    localStorage.setItem(STORAGE_KEY_IMAGE_MODEL, imageModel.trim());
    localStorage.setItem(STORAGE_KEY_RAG_COLLECTION, ragCollection);
    localStorage.setItem(STORAGE_KEY_RAG_TOP_K, String(ragTopK));
    localStorage.setItem(STORAGE_KEY_RAG_EMBEDDING_MODEL, ragEmbeddingModel.trim());
    localStorage.setItem(STORAGE_KEY_RAG_EMBEDDING_PROVIDER, ragEmbeddingProvider);

    try {
      const req: FullPipelineRequest = {
        share_text: url.trim(),
        siliconflow_api_key: apiKey.trim(),
        ai_provider: aiProvider,
        wechat_appid: wechatAppid.trim() || undefined,
        wechat_appsecret: wechatAppsecret.trim() || undefined,
        text_model: textModel.trim() || undefined,
        image_model: imageModel.trim() || undefined,
        generate_inline_images: generateInlineImages,
        rag_collection: ragCollection || undefined,
        rag_top_k: ragTopK,
        rag_embedding_model: ragEmbeddingModel.trim() || undefined,
        rag_embedding_provider: ragEmbeddingProvider,
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
    if (apiKey.trim()) localStorage.setItem(STORAGE_KEY_API, apiKey.trim());
    if (wechatAppid.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_APPID, wechatAppid.trim());
    if (wechatAppsecret.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_SECRET, wechatAppsecret.trim());
    localStorage.setItem(STORAGE_KEY_AI_PROVIDER, aiProvider);
    localStorage.setItem(STORAGE_KEY_TEXT_MODEL, textModel.trim());
    localStorage.setItem(STORAGE_KEY_IMAGE_MODEL, imageModel.trim());
    try {
      const settings = readStoredRetrySettings();
      await taskApi.retryFailedJob(jobId, {
        api_key: settings.apiKey || undefined,
        ai_provider: settings.aiProvider,
        text_model: settings.textModel || undefined,
        image_model: settings.imageModel || undefined,
        wechat_appid: settings.wechatAppid || undefined,
        wechat_appsecret: settings.wechatAppsecret || undefined,
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
    setHistoryAction({ jobId, type: "retry" });
    // 继续前先保存当前配置到 localStorage，确保读到最新值
    if (apiKey.trim()) localStorage.setItem(STORAGE_KEY_API, apiKey.trim());
    if (wechatAppid.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_APPID, wechatAppid.trim());
    if (wechatAppsecret.trim()) localStorage.setItem(STORAGE_KEY_WECHAT_SECRET, wechatAppsecret.trim());
    localStorage.setItem(STORAGE_KEY_AI_PROVIDER, aiProvider);
    localStorage.setItem(STORAGE_KEY_TEXT_MODEL, textModel.trim());
    localStorage.setItem(STORAGE_KEY_IMAGE_MODEL, imageModel.trim());
    try {
      const settings = readStoredRetrySettings();
      await taskApi.resumeJob(jobId, {
        api_key: settings.apiKey || undefined,
        ai_provider: settings.aiProvider,
        text_model: settings.textModel || undefined,
        image_model: settings.imageModel || undefined,
        wechat_appid: settings.wechatAppid || undefined,
        wechat_appsecret: settings.wechatAppsecret || undefined,
      });
      // 立即刷新 activeJob，确保活动卡片立刻从"已暂停"切换到"运行中"
      try {
        const updated = await taskApi.getJobStatus(jobId);
        setActiveJob(updated);
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
                disabled={loading || (!url && !uploadedJobId)}
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

            {/* 分隔线 + 上传区 */}
            <div className="flex items-center gap-3">
              <div className="flex-1 h-px bg-white/15" />
              <span className="text-xs text-white/35 shrink-0">或直接上传本地视频</span>
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

            {/* 上传按钮 / 进度 / 成功 */}
            <div className="overflow-hidden rounded-xl border border-dashed border-white/20 bg-white/5 backdrop-blur-sm">
              {!uploading && !uploadedJobId ? (
                <button
                  type="button"
                  onClick={() => uploadFileInputRef.current?.click()}
                  className="group w-full flex items-center justify-center gap-2.5 px-5 py-3.5 text-sm text-white/50 hover:text-white/85 transition-all duration-200"
                >
                  <svg className="w-4 h-4 shrink-0 text-[#D94E28] group-hover:scale-110 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                  </svg>
                  <span>上传视频，跳过下载直接开始处理</span>
                </button>
              ) : uploading ? (
                <div className="px-5 py-4 space-y-2.5">
                  <div className="flex items-center justify-between text-xs text-white/55">
                    <span>上传中…</span>
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
                <div className="flex items-center gap-3 px-5 py-3.5">
                  <svg className="w-4 h-4 text-emerald-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                  <span className="text-sm text-emerald-300 truncate">已上传: {uploadedFileName}</span>
                </div>
              ) : null}

              {uploadError && (
                <div className="flex items-center justify-between gap-2 px-5 pb-3.5 text-xs text-red-300">
                  <span>{uploadError}</span>
                  <button
                    type="button"
                    onClick={() => setUploadError("")}
                    className="text-white/30 hover:text-white/60 transition-colors"
                  >
                    ✕
                  </button>
                </div>
              )}
            </div>
          </div>

          {showSettings && (
            <div className="mb-8 w-full max-w-2xl overflow-hidden rounded-2xl border border-white/15 bg-black/20 backdrop-blur-xl shadow-lg shadow-black/10">
              <div className="border-b border-white/10 px-6 py-3">
                <h3 className="text-sm font-bold text-white/80">高级设置</h3>
              </div>
              <div className="space-y-4 px-6 py-5">
                {/* AI 服务商选择器 */}
                <div>
                  <label className="mb-2 block text-xs font-bold uppercase tracking-wider text-white/50">
                    AI 服务商
                  </label>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setAiProvider("siliconflow")}
                      className={`flex-1 rounded-xl border px-4 py-2.5 text-sm font-medium transition-all ${
                        aiProvider === "siliconflow"
                          ? "border-[#D94E28] bg-[#D94E28]/20 text-white"
                          : "border-white/15 bg-white/10 text-white/60 hover:bg-white/15"
                      }`}
                    >
                      SiliconFlow
                    </button>
                    <button
                      type="button"
                      onClick={() => setAiProvider("zhipu")}
                      className={`flex-1 rounded-xl border px-4 py-2.5 text-sm font-medium transition-all ${
                        aiProvider === "zhipu"
                          ? "border-[#D94E28] bg-[#D94E28]/20 text-white"
                          : "border-white/15 bg-white/10 text-white/60 hover:bg-white/15"
                      }`}
                    >
                      智谱 AI
                    </button>
                  </div>
                </div>

                <div>
                  <label className="mb-1.5 block text-xs font-bold uppercase tracking-wider text-white/50">
                    {aiProvider === "zhipu" ? "智谱 API Key" : "SiliconFlow API Key"} <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="password"
                    placeholder={aiProvider === "zhipu" ? "从智谱 AI 开放平台获取" : "sk-..."}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    className="w-full rounded-xl border border-white/15 bg-white/10 px-4 py-2.5 text-sm text-white placeholder:text-white/30 focus:border-[#D94E28]/50 focus:outline-none focus:bg-white/15 transition-colors"
                  />
                </div>

                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <label className="mb-1.5 block text-xs font-bold uppercase tracking-wider text-white/50">
                      文章生成模型
                    </label>
                    <input
                      type="text"
                      placeholder={aiProvider === "zhipu" ? "glm-4-flash（默认）" : "Qwen/Qwen3-14B（默认）"}
                      value={textModel}
                      onChange={(e) => setTextModel(e.target.value)}
                      className="w-full rounded-xl border border-white/15 bg-white/10 px-4 py-2.5 text-sm text-white placeholder:text-white/30 focus:border-[#D94E28]/50 focus:outline-none focus:bg-white/15 transition-colors"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-bold uppercase tracking-wider text-white/50">
                      图片生成模型
                    </label>
                    <input
                      type="text"
                      placeholder={aiProvider === "zhipu" ? "cogview-3（默认）" : "black-forest-labs/FLUX.1-schnell（默认）"}
                      value={imageModel}
                      onChange={(e) => setImageModel(e.target.value)}
                      className="w-full rounded-xl border border-white/15 bg-white/10 px-4 py-2.5 text-sm text-white placeholder:text-white/30 focus:border-[#D94E28]/50 focus:outline-none focus:bg-white/15 transition-colors"
                    />
                  </div>
                </div>

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

                {/* 公网 IP 查询 */}
                <div>
                  <label className="mb-1.5 block text-xs font-bold uppercase tracking-wider text-white/50">
                    公网 IP 查询
                  </label>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handleQueryIp}
                      disabled={ipLoading}
                      className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/10 px-4 py-2.5 text-sm font-bold text-white/70 transition-all hover:border-white/25 hover:bg-white/15 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <svg className={`h-4 w-4 ${ipLoading ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <circle cx="12" cy="12" r="10" />
                        <path strokeLinecap="round" d="M2 12h4m12 0h4M12 2v4m0 12v4" />
                      </svg>
                      {ipLoading ? "查询中..." : "查询公网 IP"}
                    </button>
                    {publicIp && (
                      <>
                        <span className="rounded-xl border border-white/15 bg-white/10 px-4 py-2.5 text-sm font-mono text-white/80">
                          {publicIp}
                        </span>
                        <button
                          type="button"
                          onClick={handleCopyIp}
                          title="复制 IP"
                          className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/10 px-3 py-2.5 text-sm font-bold text-white/70 transition-all hover:border-white/25 hover:bg-white/15"
                        >
                          {ipCopied ? (
                            <svg className="h-4 w-4 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <polyline points="20 6 9 17 4 12" />
                            </svg>
                          ) : (
                            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
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
                          className="inline-flex items-center gap-1.5 rounded-full border border-[#D94E28]/40 bg-[#D94E28]/15 px-3 py-2.5 text-sm font-bold text-[#FF8A65] transition-all hover:border-[#D94E28]/60 hover:bg-[#D94E28]/25"
                        >
                          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
                            <polyline points="15 3 21 3 21 9" />
                            <line x1="10" y1="14" x2="21" y2="3" />
                          </svg>
                          跳转
                        </a>
                      </>
                    )}
                  </div>
                  <p className="mt-1.5 text-[11px] text-white/30">
                    查询本机公网 IP，用于微信公众号 IP 白名单配置
                  </p>
                </div>

                <div className="flex flex-wrap gap-6 pt-1">
                  <label className="flex cursor-pointer items-center gap-2 text-sm text-white/70">
                    <input
                      type="checkbox"
                      checked={generateInlineImages}
                      onChange={(e) => setGenerateInlineImages(e.target.checked)}
                      className="h-4 w-4 rounded border-white/30 text-[#D94E28] focus:ring-[#D94E28] bg-white/10"
                    />
                    生成文中插图
                  </label>
                </div>

                {/* RAG 知识库设置 */}
                <div className="border-t border-white/10 pt-4">
                  <div className="flex items-center justify-between mb-3">
                    <label className="text-xs font-bold uppercase tracking-wider text-white/50">
                      RAG 知识库增强
                    </label>
                    <a
                      href="/knowledge"
                      className="text-[11px] text-[#FF8A65] hover:text-[#D94E28] transition-colors"
                    >
                      管理知识库 →
                    </a>
                  </div>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <div>
                      <label className="mb-1.5 block text-xs text-white/40">知识库集合</label>
                      <select
                        value={ragCollection}
                        onChange={(e) => setRagCollection(e.target.value)}
                        className="w-full rounded-xl border border-white/15 bg-white/10 px-4 py-2.5 text-sm text-white focus:border-[#D94E28]/50 focus:outline-none appearance-none"
                      >
                        <option value="" className="bg-gray-800">不使用 RAG</option>
                        {collections.map((c) => (
                          <option key={c.id} value={c.name} className="bg-gray-800">
                            {c.name} ({c.document_count} 文档, {c.chunk_count} 块)
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="mb-1.5 block text-xs text-white/40">
                        检索数量 (Top K): {ragTopK}
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
                  <div>
                    <label className="mb-1.5 block text-xs text-white/40">
                      向量模型服务商
                    </label>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => setRagEmbeddingProvider("siliconflow")}
                        className={`flex-1 rounded-xl border px-4 py-2.5 text-sm font-medium transition-all ${
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
                        className={`flex-1 rounded-xl border px-4 py-2.5 text-sm font-medium transition-all ${
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
                      className="w-full rounded-xl border border-white/15 bg-white/10 px-4 py-2.5 text-sm text-white placeholder:text-white/30 focus:border-[#D94E28]/50 focus:outline-none focus:bg-white/15 transition-colors"
                    />
                    <p className="mt-1 text-[11px] text-white/25">
                      {ragEmbeddingProvider === "zhipu"
                        ? "智谱 embedding-3 模型，用于将文本转换为向量进行相似度检索"
                        : "SiliconFlow 向量模型，用于将文本转换为向量进行相似度检索"}
                    </p>
                  </div>
                  <p className="mt-2 text-[11px] text-white/25">
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
                  <span className="text-sm text-green-400 font-bold">任务已完成，可在下方历史任务中查看详情</span>
                </div>
              )}
              {isJobPaused && (
                <div className="border-t border-white/10 px-5 py-3 flex items-center justify-between">
                  <span className="text-sm text-amber-400 font-bold">任务已暂停，可在历史任务中查看或继续</span>
                  <button
                    type="button"
                    onClick={() => handleResumeHistoryJob(activeJob.job_id)}
                    className="inline-flex items-center gap-1.5 rounded-full border border-emerald-300/25 bg-emerald-500/15 px-3 py-1.5 text-xs font-bold text-emerald-100 transition-all hover:border-emerald-300/45 hover:bg-emerald-500/25"
                  >
                    <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                      <path d="M8 5v14l11-7z" />
                    </svg>
                    继续执行
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
