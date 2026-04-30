"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import Navbar from "@/components/navbar";

// ─── 后端 API 基础地址 ──────────────────────────────────────
const API_BASE = "/api/video";

// ─── 类型定义 ──────────────────────────────────────────────
interface ParseResult {
  title: string;
  video_url: string;
  cover_url: string;
  image_url: string;
  platform: string;
  media_type: "video" | "image";
  images?: Array<{ type: string; display_url: string; url?: string }>;
  image_count: number;
  // YouTube 特殊字段
  _original_url?: string;   // YouTube 原始链接（用于 yt-dlp 下载）
  _needs_ytdl?: boolean;    // 是否需要 yt-dlp 下载
}

interface ParseResponse {
  success: boolean;
  message: string;
  data: ParseResult | null;
}

// ─── 下载状态接口 ───────────────────────────────────────────
interface DownloadState {
  downloading: boolean;
  progress: number;       // 0-100
  loadedMB: number;       // 已下载 MB
  totalMB: number;        // 总大小 MB（未知时为 0）
  speedKBs: number;       // 当前速度 KB/s
  statusText: string;     // 状态文字描述
  error: string | null;
  // 批量下载
  batchDownloading: boolean;
  batchDone: number;
  batchTotal: number;
}

const INITIAL_DOWNLOAD_STATE: DownloadState = {
  downloading: false,
  progress: 0,
  loadedMB: 0,
  totalMB: 0,
  speedKBs: 0,
  statusText: "",
  error: null,
  batchDownloading: false,
  batchDone: 0,
  batchTotal: 0,
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

export default function DownloadPage() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [result, setResult] = useState<ParseResult | null>(null);
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  // 下载进度状态
  const [dlState, setDlState] = useState<DownloadState>(INITIAL_DOWNLOAD_STATE);
  // 用于取消请求的 ref
  const abortRef = useRef<AbortController | null>(null);
  // 速度计算用的定时器 ref
  const speedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const prevLoadedRef = useRef<number>(0);
  // 批量下载取消标志（用 ref 绕过 React 闭包快照问题）
  const batchCancelRef = useRef<boolean>(false);
  // YouTube 下载：当前 download_id（用于取消）
  const ytDownloadIdRef = useRef<string>("");

  // 重置状态
  const resetState = () => {
    setResult(null);
    setErrorMsg("");
    setCurrentImageIndex(0);
    setDlState(INITIAL_DOWNLOAD_STATE);
  };

  // 清理速度计时器
  const clearSpeedTimer = useCallback(() => {
    if (speedTimerRef.current) {
      clearInterval(speedTimerRef.current);
      speedTimerRef.current = null;
    }
  }, []);

  // 格式化文件大小显示
  const formatSize = (mb: number) => {
    if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
    return `${mb.toFixed(1)} MB`;
  };

  // 解析视频链接
  const handleParse = async () => {
    if (!url.trim()) {
      setErrorMsg("请输入分享链接");
      return;
    }

    setLoading(true);
    resetState();

    try {
      const resp = await fetch(`${API_BASE}/parse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim() }),
      });

      const data: ParseResponse = await resp.json();

      if (!data.success || !data.data) {
        setErrorMsg(data.message || "解析失败，请检查链接是否正确");
        return;
      }

      setResult(data.data);
    } catch (error: unknown) {
      console.error("解析失败:", error);
      if (error instanceof Response) {
        setErrorMsg(`请求失败 (${error.status})，请检查后端是否启动`);
      } else if (error instanceof Error) {
        if (
          error.message.includes("fetch") ||
          error.message.includes("network") ||
          error.message.includes("Failed")
        ) {
          setErrorMsg("无法连接到后端服务，请确认后端已启动 (http://127.0.0.1:8000)");
        } else {
          setErrorMsg(error.message || "解析失败，请稍后重试");
        }
      } else {
        setErrorMsg("未知错误，请重试");
      }
    } finally {
      setLoading(false);
    }
  };

  // 获取封面预览 URL（通过后端代理）
  const getPreviewUrl = (imgUrl: string, platform: string) => {
    return `${API_BASE}/preview?url=${encodeURIComponent(imgUrl)}&platform=${platform}`;
  };

  // 取消下载
  const cancelDownload = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    // 如果是 YouTube 下载，调用取消端点
    const ytId = ytDownloadIdRef.current;
    if (ytId) {
      fetch(`${API_BASE}/youtube-cancel?download_id=${ytId}`, { method: "POST" }).catch(() => {});
      ytDownloadIdRef.current = "";
    }
    clearSpeedTimer();
    setDlState((prev) => ({
      ...prev,
      downloading: false,
      statusText: "已取消",
    }));
  }, [clearSpeedTimer]);

  // 流式下载 + 进度追踪
  const handleDownload = async (
    fileUrl: string,
    platform: string,
    mediaType: string,
    filename: string
  ) => {
    // 取消之前的下载
    if (abortRef.current) abortRef.current.abort();
    clearSpeedTimer();
    prevLoadedRef.current = 0;

    // 清理之前的 YouTube download_id
    ytDownloadIdRef.current = "";

    const controller = new AbortController();
    abortRef.current = controller;

    setDlState({
      ...INITIAL_DOWNLOAD_STATE,
      downloading: true,
      statusText: "正在连接…",
    });

    // ── YouTube 特殊处理：使用 fetch 流式下载 + 进度追踪 ──
    if (platform === "youtube") {
      let totalBytes = 0;
      let totalMB = 0;

      // 1. 先预获取元数据（含文件大小）
      try {
        const metaResp = await fetch(`${API_BASE}/youtube-metadata?url=${encodeURIComponent(fileUrl)}`);
        if (metaResp.ok) {
          const metaData = await metaResp.json();
          if (metaData.success && metaData.filesize) {
            totalBytes = metaData.filesize;
            totalMB = totalBytes / 1048576;
          }
        }
      } catch (e) {
        console.warn("[!] YouTube元数据获取失败，使用无总量模式:", e);
      }

      // 生成 download_id（用于取消）
      const downloadId = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
      ytDownloadIdRef.current = downloadId;

      setDlState((prev) => ({
        ...prev,
        totalMB,
        statusText: "正在下载…",
      }));

      try {
        const downloadUrl = `${API_BASE}/download?url=${encodeURIComponent(fileUrl)}&platform=${platform}&media_type=${mediaType}&download_id=${downloadId}`;

        const resp = await fetch(downloadUrl, { signal: controller.signal });

        if (!resp.ok && resp.status !== 200 && resp.status !== 206) {
          const errText = await resp.text();
          throw new Error(`下载失败: ${resp.status} ${errText}`);
        }

        // 优先使用响应头的 Content-Length（如果元数据没拿到）
        if (totalBytes === 0) {
          const cl = resp.headers.get("content-length");
          if (cl) {
            totalBytes = parseInt(cl, 10);
            totalMB = totalBytes / 1048576;
            setDlState((prev) => ({ ...prev, totalMB }));
          }
        }

        const reader = resp.body?.getReader();
        if (!reader) throw new Error("无法获取下载流");

        const chunks: Uint8Array[] = [];
        let loaded = 0;

        // 速度计算定时器（每 500ms）
        speedTimerRef.current = setInterval(() => {
          const deltaLoaded = loaded - prevLoadedRef.current;
          const speedKB = deltaLoaded / 1024 * 2;
          setDlState((prev) => ({
            ...prev,
            speedKBs: Math.round(speedKB),
          }));
          prevLoadedRef.current = loaded;
        }, 500);

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          if (!value || value.length === 0) continue;
          chunks.push(value);
          loaded += value.length;
          const loadedMB = loaded / 1048576;

          if (totalBytes > 0) {
            const pct = Math.min(Math.round((loaded / totalBytes) * 100), 99);
            setDlState((prev) => ({
              ...prev,
              progress: Math.max(prev.progress, pct),
              loadedMB,
              statusText: `已下载 ${formatSize(loadedMB)} / ${formatSize(totalMB)}`,
            }));
          } else {
            setDlState((prev) => ({
              ...prev,
              loadedMB,
              statusText: `已下载 ${formatSize(loadedMB)}…`,
            }));
          }
        }

        clearSpeedTimer();

        // 合并 chunk 并触发下载
        const blob = new Blob(chunks as BlobPart[]);
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = blobUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(blobUrl);

        setDlState({
          ...INITIAL_DOWNLOAD_STATE,
          progress: 100,
          loadedMB: totalMB || loaded / 1048576,
          totalMB: totalMB || loaded / 1048576,
          statusText: "下载完成 ✓",
        });

        setTimeout(() => setDlState(INITIAL_DOWNLOAD_STATE), 3000);
      } catch (error: unknown) {
        clearSpeedTimer();
        if ((error as Error).name === "AbortError") {
          return;
        }
        const errMsg = error instanceof Error ? error.message : "下载失败";
        setDlState((prev) => ({
          ...prev,
          downloading: false,
          error: errMsg,
          statusText: "下载失败",
        }));
        setTimeout(() => setDlState((p) => ({ ...p, error: null })), 4000);
      }

      ytDownloadIdRef.current = "";
      abortRef.current = null;
      return;
    }

    // ── 其他平台：原有流式下载逻辑 ──
    try {
      const downloadUrl = `${API_BASE}/download?url=${encodeURIComponent(fileUrl)}&platform=${platform}&media_type=${mediaType}`;

      const resp = await fetch(downloadUrl, { signal: controller.signal });

      if (!resp.ok && resp.status !== 200 && resp.status !== 206) {
        const errText = await resp.text();
        throw new Error(`下载失败: ${resp.status} ${errText}`);
      }

      // 从响应头获取总大小
      const contentLength = resp.headers.get("content-length");
      const totalBytes = contentLength ? parseInt(contentLength, 10) : 0;
      const totalMB = totalBytes > 0 ? totalBytes / 1048576 : 0;

      // 如果没有 Content-Length，使用不确定模式
      if (totalMB === 0) {
        setDlState((prev) => ({
          ...prev,
          totalMB: 0,
          statusText: "正在下载…",
        }));
      }

      // 使用 reader 流式读取
      const reader = resp.body?.getReader();
      if (!reader) throw new Error("无法获取下载流");

      const chunks: Uint8Array[] = [];
      let loaded = 0;

      // 启动速度计算定时器（每 500ms 更新一次速度）
      speedTimerRef.current = setInterval(() => {
        const deltaLoaded = loaded - prevLoadedRef.current;
        const speedKB = deltaLoaded / 1024 * 2; // *2 因为间隔是500ms
        setDlState((prev) => ({
          ...prev,
          speedKBs: Math.round(speedKB),
        }));
        prevLoadedRef.current = loaded;
      }, 500);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        loaded += value.length;

        const loadedMB = loaded / 1048576;

        // 计算进度百分比
        const progress =
          totalBytes > 0 ? Math.min(Math.round((loaded / totalBytes) * 100), 99) : Math.min(Math.round(loadedMB % 10 * 10), 90);

        setDlState((prev) => ({
          ...prev,
          progress: totalBytes > 0 ? progress : (prev.progress >= 85 ? 88 : prev.progress + 2),
          loadedMB,
          ...(totalMB > 0 ? { totalMB } : {}),
          ...(totalBytes === 0 ? { statusText: `已下载 ${formatSize(loadedMB)}…` } : { statusText: `已下载 ${formatSize(loadedMB)} / ${formatSize(totalMB)}` }),
        }));
      }

      clearSpeedTimer();

      // 合并所有 chunk 为 Blob 并触发下载
      const blob = new Blob(chunks as BlobPart[]);
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);

      // 完成
      setDlState({
        ...INITIAL_DOWNLOAD_STATE,
        progress: 100,
        loadedMB: totalMB || loaded / 1048576,
        ...(totalMB > 0 ? { totalMB } : { totalMB: loaded / 1048576 }),
        statusText: "下载完成 ✓",
      });

      // 3秒后自动隐藏完成提示
      setTimeout(() => {
        setDlState(INITIAL_DOWNLOAD_STATE);
      }, 3000);
    } catch (error: unknown) {
      clearSpeedTimer();
      if ((error as Error).name === "AbortError") {
        // 用户主动取消，不报错
        return;
      }
      console.error("下载失败:", error);
      const msg = error instanceof Error ? error.message : "下载失败，请重试";
      setDlState((prev) => ({
        ...prev,
        downloading: false,
        error: msg,
        statusText: "下载失败",
      }));
      setTimeout(() => {
        setDlState((p) => ({ ...p, error: null }));
      }, 4000);
    } finally {
      abortRef.current = null;
    }
  };

  // ── 批量下载所有图片（逐个触发下载） ──
  const handleDownloadAll = async () => {
    if (!result?.images || result.images.length === 0) return;

    const images = result.images.filter((img) => img.type !== "video" && img.display_url);
    if (images.length === 0) return;

    // 如果已在批量下载中，则取消
    if (dlState.batchDownloading) {
      batchCancelRef.current = true;
      setDlState((prev) => ({
        ...prev,
        statusText: "正在取消…",
      }));
      return;
    }

    // 重置取消标志，开始批量下载
    batchCancelRef.current = false;
    setDlState((prev) => ({
      ...INITIAL_DOWNLOAD_STATE,
      batchDownloading: true,
      batchDone: 0,
      batchTotal: images.length,
      statusText: `准备批量下载 ${images.length} 张图片…`,
    }));

    let successCount = 0;

    for (let i = 0; i < images.length; i++) {
      // 通过 ref 检查是否被取消（不受 React 闭包快照影响）
      if (batchCancelRef.current) break;

      const img = images[i];
      setDlState((prev) => ({
        ...prev,
        batchDone: i,
        statusText: `正在下载第 ${i + 1}/${images.length} 张…`,
      }));

      try {
        const downloadUrl = `${API_BASE}/download?url=${encodeURIComponent(img.display_url)}&platform=${result!.platform}&media_type=image`;
        const resp = await fetch(downloadUrl);

        // 每次异步操作后再次检查取消标志
        if (batchCancelRef.current) break;

        if (!resp.ok || (resp.status !== 200 && resp.status !== 206)) {
          console.warn(`图片 ${i + 1} 下载失败: ${resp.status}`);
          continue;
        }

        const blob = await resp.blob();
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = blobUrl;
        a.download = `image_${i + 1}.jpg`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(blobUrl);

        successCount++;
        // 稍微间隔，避免浏览器拦截
        await new Promise((r) => setTimeout(r, 300));
      } catch (e) {
        console.warn(`图片 ${i + 1} 下载异常:`, e);
      }
    }

    // 批量完成
    const wasCancelled = batchCancelRef.current;
    batchCancelRef.current = false;
    setDlState((prev) => ({
      ...INITIAL_DOWNLOAD_STATE,
      progress: wasCancelled ? prev.progress : 100,
      statusText: wasCancelled ? `已取消，已下载 ${successCount}/${images.length} 张` : `完成！共下载 ${successCount}/${images.length} 张图片 ✓`,
    }));

    setTimeout(() => setDlState(INITIAL_DOWNLOAD_STATE), 4000);
  };

  // 获取平台名称中文
  const getPlatformName = (platformId: string) => {
    const map: Record<string, string> = {
      douyin: "抖音",
      bilibili: "哔哩哔哩",
      tiktok: "TikTok",
      kuaishou: "快手",
      instagram: "Instagram",
      x: "X (Twitter)",
      youtube: "YouTube",
    };
    return map[platformId] || platformId;
  };

  // 获取当前显示的图片 URL
  const getCurrentImageUrl = (): string | null => {
    if (!result) return null;
    const images = result.images || [];
    if (images.length > 0 && currentImageIndex < images.length) {
      return images[currentImageIndex].display_url || null;
    }
    return result.cover_url || null;
  };

  // 当前图片是否为视频类型
  const isCurrentVideo = (): boolean => {
    if (!result || !result.images || currentImageIndex >= result.images.length) return false;
    return result.images[currentImageIndex]?.type === "video";
  };

  // 安全获取图片总数（兜底防御）
  const getImageCount = (): number => {
    if (!result) return 0;
    if (typeof result.image_count === "number") return result.image_count;
    const images = result.images || [];
    return images.length || (result.media_type === "image" ? 1 : 0);
  };

  return (
    <div className="min-h-screen text-white">
      <Navbar />

      <main className="relative flex flex-col items-center overflow-hidden px-4 pb-16 pt-28 sm:px-6 sm:pt-32 lg:px-8">
        <VideoBackground />
        <div className="relative z-10 flex w-full max-w-3xl flex-col items-center text-center">

          {/* 标题 */}
          <h1 className="hero-headline mb-12">短视频下载平台</h1>

          {/* 输入框 + 解析按钮 */}
          <div className="w-full max-w-2xl space-y-3">
            <div className="floating-input">
              <input
                id="download-url"
                type="text"
                placeholder="粘贴抖音 / Instagram / B站 / TikTok 等分享链接…"
                value={url}
                onChange={(e) => { setUrl(e.target.value); if (errorMsg && e.target.value.trim()) setErrorMsg(""); }}
                onKeyDown={(e) => e.key === "Enter" && handleParse()}
                className="min-w-0 flex-1 border-none bg-transparent text-base font-medium text-white placeholder:text-white/40 focus:outline-none focus:ring-0 pl-5 pr-3 py-3"
              />
              <button
                type="button"
                onClick={handleParse}
                disabled={loading || !url}
                className="btn-brand-inner disabled:pointer-events-none disabled:opacity-50 shrink-0"
              >
                {loading ? "解析中…" : "解析"}
              </button>
            </div>

            {/* 错误提示 */}
            {errorMsg && (
              <div className="rounded-xl border border-red-400/30 bg-red-500/20 backdrop-blur-md px-4 py-3 text-left text-sm text-red-200">
                {errorMsg}
              </div>
            )}
          </div>

          {/* ── 解析结果区域 ─────────────────────────────── */}
          {result && (
            <div className="mt-10 w-full max-w-2xl animate-in fade-in slide-in-from-bottom-4 duration-500">
              {/* 信息卡片 */}
              <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-xl p-6 space-y-5">
                {/* 标题 + 平台标签 */}
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <p className="text-base font-semibold text-white truncate" title={result.title}>
                      {result.title || "未获取到标题"}
                    </p>
                    <span className="mt-1 inline-flex items-center rounded-full bg-[#D94E28]/20 px-2.5 py-0.5 text-xs font-medium text-[#FF8A65]">
                      {getPlatformName(result.platform)}
                    </span>
                    {result.media_type === "image" && (
                      <span className="ml-2 inline-flex items-center rounded-full bg-blue-500/20 px-2.5 py-0.5 text-xs font-medium text-blue-300">
                        图片
                      </span>
                    )}
                  </div>
                </div>

                {/* ── 图片/视频展示区 ── */}
                {getCurrentImageUrl() && (
                  <div className="space-y-3">
                    {/* 大图/视频预览 */}
                    <div className="relative overflow-hidden rounded-xl bg-black/30">
                      {isCurrentVideo() && result.images?.[currentImageIndex]?.url ? (
                        <video
                          controls
                          className="w-full aspect-video object-cover"
                          poster={getPreviewUrl(getCurrentImageUrl()!, result.platform)}
                          preload="metadata"
                        >
                          <source src={getPreviewUrl(result.images[currentImageIndex].url!, result.platform)} type="video/mp4" />
                        </video>
                      ) : (
                        <img
                          src={getPreviewUrl(getCurrentImageUrl()!, result.platform)}
                          alt={`${result.title || "图片"} - ${currentImageIndex + 1}`}
                          className="w-full rounded-xl object-contain max-h-[400px]"
                          loading="lazy"
                        />
                      )}
                    </div>

                    {/* ── 多图轮播：缩略图条 + 两侧切换按钮 ── */}
                    {result.images && getImageCount() > 1 && (
                      <div className="relative group/carousel">
                        {/* 左切换按钮 */}
                        <button
                          onClick={() => setCurrentImageIndex((i) => Math.max(0, i - 1))}
                          disabled={currentImageIndex === 0}
                          className="absolute left-0 top-1/2 -translate-y-1/2 z-10 flex h-8 w-8 items-center justify-center rounded-full bg-black/50 backdrop-blur-sm text-white/80 hover:bg-[#D94E28] hover:text-white disabled:opacity-20 disabled:cursor-default transition-all shadow-lg -translate-x-1"
                        >
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
                          </svg>
                        </button>

                        {/* 缩略图滚动容器 */}
                        <div className="overflow-x-auto scrollbar-hide px-6">
                          <div
                            className="flex gap-2.5 py-2"
                            role="tablist"
                          >
                            {(result.images || []).map((img, idx) => {
                              const isActive = idx === currentImageIndex;
                              return (
                                <button
                                  key={idx}
                                  role="tab"
                                  aria-selected={isActive}
                                  onClick={() => {
                                    setCurrentImageIndex(idx);
                                    // 滚动到可见区域
                                    const el = document.getElementById(`thumb-${idx}`);
                                    el?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
                                  }}
                                  className={`relative shrink-0 overflow-hidden rounded-lg transition-all duration-200 ${
                                    isActive
                                      ? "ring-2 ring-[#D94E28] ring-offset-2 ring-offset-transparent scale-[1.05] shadow-md"
                                      : "ring-1 ring-white/10 opacity-60 hover:opacity-90 hover:ring-white/25"
                                  }`}
                                  style={{ width: "72px", height: "72px" }}
                                >
                                  <img
                                    id={`thumb-${idx}`}
                                    src={getPreviewUrl(img.display_url, result.platform)}
                                    alt={`第${idx + 1}张`}
                                    className="h-full w-full object-cover"
                                    loading="lazy"
                                  />
                                  {/* 序号角标 */}
                                  <span className="absolute bottom-0.5 right-0.5 rounded bg-black/60 px-1 py-0.5 text-[9px] font-medium tabular-nums leading-none text-white/80">
                                    {idx + 1}
                                  </span>
                                </button>
                              );
                            })}
                          </div>
                        </div>

                        {/* 右切换按钮 */}
                        <button
                          onClick={() => setCurrentImageIndex((i) => Math.min(getImageCount() - 1, i + 1))}
                          disabled={currentImageIndex >= getImageCount() - 1}
                          className="absolute right-0 top-1/2 -translate-y-1/2 z-10 flex h-8 w-8 items-center justify-center rounded-full bg-black/50 backdrop-blur-sm text-white/80 hover:bg-[#D94E28] hover:text-white disabled:opacity-20 disabled:cursor-default transition-all shadow-lg translate-x-1"
                        >
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                          </svg>
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {/* 操作按钮组 */}
                <div className="flex flex-wrap gap-3 justify-center">
                  {/* 主下载按钮（视频） */}
                  {(() => {
                    // 判断是否有可下载的视频/内容链接
                    const hasVideoUrl = !!result.video_url;
                    const isYouTube = result.platform === "youtube";
                    const isX = result.platform === "x";
                    // YouTube 和 X 都需要用原始链接走后端下载
                    const showDownload = hasVideoUrl || ((isYouTube || isX) && !!result._original_url);
                    
                    if (!showDownload) return null;
                    
                    return (
                    <button
                      onClick={() =>
                        dlState.downloading
                          ? cancelDownload()
                          :                         handleDownload(
                              // YouTube / X 用原始链接走后端 yt-dlp，其他平台用 video_url 直链
                              (isYouTube || isX) ? result._original_url! : result.video_url!,
                              result.platform,
                              "video",
                              `${result.title || "video"}.mp4`
                            )
                      }
                      disabled={!dlState.downloading && !!dlState.error}
                      className={`btn-brand !px-6 !py-2.5 text-sm font-semibold transition-all active:scale-[0.98] ${
                        dlState.downloading
                          ? "!bg-[#c44322] cursor-pointer"
                          : "hover:scale-[1.02]"
                      } ${dlState.error ? "opacity-70" : ""}`}
                    >
                      {dlState.downloading ? (
                        <span className="flex items-center gap-2">
                          <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
                            <rect x="6" y="6" width="12" height="12" rx="2" />
                          </svg>
                          取消
                        </span>
                      ) : (
                        <span className="flex items-center gap-2">
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10" />
                          </svg>
                          下载视频
                        </span>
                      )}
                    </button>
                    );
                  })()}

                  {/* 轮播图：当前选中图片的下载 */}
                  {result.images && getImageCount() > 1 && isCurrentVideo() === false && result.images[currentImageIndex]?.display_url && (
                    <button
                      onClick={() =>
                        handleDownload(
                          result.images![currentImageIndex].display_url,
                          result.platform,
                          "image",
                          `image_${currentImageIndex + 1}.jpg`
                        )
                      }
                      disabled={dlState.downloading || dlState.batchDownloading}
                      className="inline-flex items-center gap-2 rounded-xl border border-white/15 bg-white/5 px-5 py-2.5 text-sm font-medium text-white/80 backdrop-blur-sm transition-all hover:bg-white/10 hover:border-white/25 active:scale-[0.98] disabled:opacity-50"
                    >
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                      </svg>
                      下载此图 ({currentImageIndex + 1}/{getImageCount()})
                    </button>
                  )}

                  {/* 全部下载按钮 */}
                  {result.images && getImageCount() > 1 && (
                    <button
                      onClick={() => handleDownloadAll()}
                      disabled={dlState.downloading}
                      className={`inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-sm font-semibold transition-all active:scale-[0.98] disabled:opacity-50 ${
                        dlState.batchDownloading
                          ? "bg-red-500/20 border border-red-500/40 text-red-300 hover:bg-red-500/30"
                          : "border border-[#D94E28]/30 bg-[#D94E28]/10 text-[#FF8A65] hover:bg-[#D94E28]/20 hover:border-[#D94E28]/50"
                      }`}
                    >
                      {dlState.batchDownloading ? (
                        <>
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                          </svg>
                          取消 ({dlState.batchDone}/{getImageCount()})
                        </>
                      ) : (
                        <>
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                            <path strokeLinecap="round" strokeLinejoin="round" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10" />
                          </svg>
                          全部下载 ({getImageCount()}张)
                        </>
                      )}
                    </button>
                  )}

                  {/* 仅单张图片时显示下载按钮 */}
                  {!result.video_url && result.media_type === "image" && (getImageCount() <= 1) && result.cover_url && (
                    <button
                      onClick={() =>
                        handleDownload(
                          result.cover_url,
                          result.platform,
                          "image",
                          `${result.title || "image"}.jpg`
                        )
                      }
                      disabled={dlState.downloading}
                      className="btn-brand !px-6 !py-2.5 text-sm font-semibold disabled:opacity-50 transition-all hover:scale-[1.02] active:scale-[0.98]"
                    >
                      {dlState.downloading ? "下载中…" : (
                        <span className="flex items-center gap-2">
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                          </svg>
                          下载图片
                        </span>
                      )}
                    </button>
                  )}
                </div>

                {/* ══════════ 下载进度条 ══════════ */}
                {(dlState.downloading || dlState.batchDownloading || dlState.progress === 100 || dlState.error) && (
                  <div className={`animate-in fade-in slide-in-from-bottom-2 duration-300 rounded-xl border ${
                    dlState.error
                      ? "border-red-400/20 bg-red-500/10"
                      : dlState.progress === 100
                        ? "border-emerald-400/20 bg-emerald-500/10"
                        : "border-white/10 bg-white/[0.04] backdrop-blur-md"
                  } p-4 space-y-3`}>
                    {/* 顶部：状态行 */}
                    <div className="flex items-center justify-between gap-3">
                      {/* 左侧：图标+文字 */}
                      <div className="flex items-center gap-2.5 min-w-0">
                        {dlState.progress === 100 ? (
                          /* 完成图标 */
                          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-500/20">
                            <svg className="h-4 w-4 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                            </svg>
                          </div>
                        ) : dlState.error ? (
                          /* 错误图标 */
                          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-red-500/20">
                            <svg className="h-4 w-4 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                            </svg>
                          </div>
                        ) : dlState.downloading ? (
                          /* 下载中：旋转箭头 */
                          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#D94E28]/20">
                            <svg className="animate-spin h-4 w-4 text-[#FF8A65]" viewBox="0 0 24 24">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                            </svg>
                          </div>
                        ) : dlState.batchDownloading ? (
                          /* 批量下载中：批量图标 */
                          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-500/20">
                            <svg className="animate-spin h-4 w-4 text-blue-300" viewBox="0 0 24 24">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                            </svg>
                          </div>
                        ) : null}

                        <span className={`text-sm truncate ${
                          dlState.error ? "text-red-300" : dlState.progress === 100 ? "text-emerald-300" : "text-white/80"
                        }`}>
                          {dlState.statusText || (dlState.downloading ? "准备中…" : (dlState.batchDownloading ? "准备批量下载…" : ""))}
                        </span>
                      </div>

                      {/* 右侧：数据信息 */}
                      <div className="shrink-0 flex items-center gap-3 text-xs tabular-nums">
                        {dlState.speedKBs > 0 && dlState.downloading && (
                          <span className="hidden sm:inline-flex items-center text-[#FF8A65]/90 font-medium">
                            ↓{dlState.speedKBs} KB/s
                          </span>
                        )}
                        {(dlState.totalMB > 0 || dlState.loadedMB > 0) && (
                          <span className="text-white/50">
                            {formatSize(dlState.loadedMB)}
                            {dlState.totalMB > 0 && ` / ${formatSize(dlState.totalMB)}`}
                          </span>
                        )}
                        {dlState.progress > 0 && (
                          <span className={`font-semibold w-10 text-right ${
                            dlState.progress === 100 ? "text-emerald-400" :
                            dlState.error ? "text-red-300" :
                            "text-[#FF8A65]"
                          }`}>
                            {dlState.progress}%
                          </span>
                        )}
                      </div>
                    </div>

                    {/* 进度条轨道 */}
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-black/20">
                      <div
                        className={`h-full rounded-full transition-all duration-300 ease-out ${
                          dlState.error
                            ? "bg-red-400/60"
                            : dlState.progress === 100
                              ? "bg-emerald-400"
                              : dlState.batchDownloading
                                ? "bg-gradient-to-r from-blue-500 to-blue-400"
                                : "bg-gradient-to-r from-[#D94E28] to-[#FF8A65]"
                        }`}
                        style={{
                          width: dlState.error ? "100%" : (dlState.batchDownloading && dlState.batchTotal > 0 ? `${Math.round((dlState.batchDone / dlState.batchTotal) * 100)}%` : `${Math.min(dlState.progress, 100)}%`),
                          transitionDuration: dlState.downloading || dlState.batchDownloading ? "150ms" : "600ms",
                        }}
                      />
                    </div>

                    {/* 错误信息 */}
                    {dlState.error && (
                      <p className="text-xs text-red-300/80">{dlState.error}</p>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

        </div>
      </main>
    </div>
  );
}
