"use client";

import { Flame, Loader2, RefreshCw, Sparkles, TrendingUp } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const PANEL_HEIGHT = 640;
const HANDLE_SIZE = 52;
const CHAIN_DROOP = 28;

// SSR 安全默认值
const DEFAULT_WIDTH = 1200;
const DEFAULT_CHAIN_LEN = 200;

interface HotEntry {
  rank: number;
  title: string;
  article_url: string;
  score: string;
  source: string;
}

interface HotBoard {
  id: string;
  title: string;
  source_url: string;
  accent: string;
  updated_at: string;
  entries: HotEntry[];
}

interface HotBoardsResponse {
  success: boolean;
  message: string;
  boards: HotBoard[];
  errors?: string[];
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function formatBoardTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚更新";
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function formatBoardSourceLabel(sourceUrl: string) {
  if (!sourceUrl) return "聚合热榜";
  if (sourceUrl.includes("newsnow")) return "NewsNow";
  if (sourceUrl.includes("tophub")) return "TopHub";
  try {
    const hostname = new URL(sourceUrl).hostname.replace(/^www\./, "");
    return hostname || "聚合热榜";
  } catch {
    return "聚合热榜";
  }
}

export default function HotSearchShelf() {
  const [mounted, setMounted] = useState(false);

  // ── 动态尺寸 ──
  const [pageWidth, setPageWidth] = useState(DEFAULT_WIDTH);
  const [pageHeight, setPageHeight] = useState(800);
  const initialChainLen = pageWidth / 6; // 页面宽度 / 6

  // ── 链头位置（可自由移动） ──
  // 初始：右侧，Y = 初始链条长度
  const [handleX, setHandleX] = useState(DEFAULT_WIDTH * 0.8);
  const [handleY, setHandleY] = useState(DEFAULT_CHAIN_LEN);
  // 锚点 X 跟随链头左右移动，始终垂直悬挂
  const anchorX = handleX;
  const anchorY = 0;
  const [isDragging, setIsDragging] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);

  const [boards, setBoards] = useState<HotBoard[]>([]);
  const [activeBoardId, setActiveBoardId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [partialErrors, setPartialErrors] = useState<string[]>([]);

  const entriesRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    startHandleX: number;
    startHandleY: number;
  } | null>(null);

  // ── 客户端初始化 ──
  useEffect(() => {
    const w = window.innerWidth;
    const h = window.innerHeight;
    setPageWidth(w);
    setPageHeight(h);
    setHandleX(w * 0.8);
    setHandleY(w / 6);
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    const onResize = () => {
      setPageWidth(window.innerWidth);
      setPageHeight(window.innerHeight);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [mounted]);

  // ── 数据加载 ──
  const loadBoards = useCallback(async (forceRefresh = false) => {
    try {
      setLoading(true);
      setError("");
      const url = new URL("/api/hot/boards", window.location.origin);
      if (forceRefresh) url.searchParams.set("force_refresh", "true");
      const resp = await fetch(url.toString(), { cache: "no-store" });
      if (!resp.ok) throw new Error(`请求失败 (${resp.status})`);
      const data: HotBoardsResponse = await resp.json();
      if (!data.success) throw new Error(data.message || "获取热榜失败");
      setBoards(data.boards || []);
      setPartialErrors(data.errors || []);
      setActiveBoardId((c) => c || data.boards?.[0]?.id || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "获取热榜失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBoards();
  }, [loadBoards]);

  const activeBoard = useMemo(
    () => boards.find((b) => b.id === activeBoardId) || boards[0] || null,
    [activeBoardId, boards]
  );

  // 切换榜单时滚回顶部
  useEffect(() => {
    entriesRef.current?.scrollTo(0, 0);
  }, [activeBoardId]);

  // ── 自由拖拽（X + Y） ──
  const handlePointerDown = (e: React.PointerEvent<HTMLButtonElement>) => {
    dragRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      startHandleX: handleX,
      startHandleY: handleY,
    };
    setIsDragging(true);
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLButtonElement>) => {
    const d = dragRef.current;
    if (!d || d.pointerId !== e.pointerId) return;
    const dx = e.clientX - d.startX;
    const dy = e.clientY - d.startY;
    setHandleX(clamp(d.startHandleX + dx, 32, pageWidth - 32));
    setHandleY(Math.max(d.startHandleY + dy, 32));
  };

  const handlePointerUp = (e: React.PointerEvent<HTMLButtonElement>) => {
    const d = dragRef.current;
    if (!d || d.pointerId !== e.pointerId) return;
    dragRef.current = null;
    setIsDragging(false);
    e.currentTarget.releasePointerCapture(e.pointerId);

    // 链条始终垂直，只看 Y 方向拉伸
    if (handleY > initialChainLen * 0.6) {
      setIsExpanded(true);
    } else {
      setIsExpanded(false);
    }

    // Y 回弹到初始长度，X 保持当前位置（锚点跟随）
    setHandleY(initialChainLen);
  };

  const closePanel = () => {
    setIsExpanded(false);
    setHandleY(initialChainLen);
  };

  // ── 链条 SVG 参数 ──
  const chainLen = handleY - anchorY; // 垂直链条，长度 = Y 差
  const stretchRatio = chainLen / initialChainLen;
  // 垂直链条 + 轻微侧向下垂，模拟自然悬挂
  const midX = anchorX + CHAIN_DROOP * 0.5;
  const midY = (anchorY + handleY) / 2;
  const chainOpacity = clamp(0.7 + stretchRatio * 0.15, 0.7, 1);

  // SSR 阶段
  if (!mounted) {
    return (
      <>
        <div className="pointer-events-none opacity-0 fixed inset-0 z-[55]" />
        <div
          className="fixed z-[60] w-[min(1080px,calc(100vw-20px))] overflow-hidden rounded-b-[28px] border border-white/15 bg-[#120b08]/92 shadow-[0_30px_90px_rgba(0,0,0,0.38)] backdrop-blur-2xl"
          style={{ top: 0, left: "50%", height: PANEL_HEIGHT, transform: `translate(-50%, -${PANEL_HEIGHT + 20}px)` }}
        >
          <div className="relative h-full bg-[radial-gradient(circle_at_top_left,rgba(236,102,57,0.22),transparent_42%),radial-gradient(circle_at_top_right,rgba(255,221,186,0.15),transparent_38%),linear-gradient(180deg,rgba(41,24,20,0.96),rgba(12,8,7,0.98))]">
            <div className="flex h-full flex-col">
              <div className="flex items-start justify-between gap-4 border-b border-white/10 px-6 pb-4 pt-10">
                <div>
                  <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.24em] text-[#ffb08f]">
                    <Sparkles className="h-3.5 w-3.5" />
                    今日热搜二楼
                  </div>
                  <h2 className="mt-2 text-2xl font-bold tracking-tight text-white">拉下链条查看今日热搜</h2>
                </div>
              </div>
              <div className="flex min-h-0 flex-1 items-center justify-center text-white/55">加载中...</div>
            </div>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      {/* ── 背景遮罩 ── */}
      <div
        className={`fixed inset-0 z-[55] bg-black/30 transition-opacity duration-500 ${
          isExpanded ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"
        }`}
        onClick={closePanel}
      />

      {/* ── 热搜面板 ── */}
      <div
        className="fixed z-[60] w-[min(1080px,calc(100vw-20px))] overflow-hidden rounded-b-[28px] border border-white/15 bg-[#120b08]/92 shadow-[0_30px_90px_rgba(0,0,0,0.38)] backdrop-blur-2xl"
        style={{
          top: 0,
          left: "50%",
          height: PANEL_HEIGHT,
          transform: isExpanded ? "translate(-50%, 0)" : `translate(-50%, -${PANEL_HEIGHT + 20}px)`,
          transition: isDragging ? "none" : "transform 500ms cubic-bezier(0.34, 1.56, 0.64, 1)",
        }}
      >
        <div className="relative h-full bg-[radial-gradient(circle_at_top_left,rgba(236,102,57,0.22),transparent_42%),radial-gradient(circle_at_top_right,rgba(255,221,186,0.15),transparent_38%),linear-gradient(180deg,rgba(41,24,20,0.96),rgba(12,8,7,0.98))]">
          <div className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-[#ffb37f1f] to-transparent" />
          <div className="flex h-full flex-col">
            <div className="flex items-start justify-between gap-4 border-b border-white/10 px-6 pb-4 pt-10">
              <div>
                <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.24em] text-[#ffb08f]">
                  <Sparkles className="h-3.5 w-3.5" />
                  今日热搜二楼
                </div>
                <h2 className="mt-2 text-2xl font-bold tracking-tight text-white">拉下链条查看今日热搜</h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-white/55">
                  按住链头拖动，松手后展开热搜面板。
                </p>
              </div>
              <button
                type="button"
                onClick={() => loadBoards(true)}
                disabled={loading}
                className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-4 py-2 text-sm font-semibold text-white/80 transition-all hover:border-white/25 hover:bg-white/15 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
                刷新热榜
              </button>
            </div>

            <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
              <aside className="scrollbar-hide overflow-y-auto border-b border-white/10 px-4 py-4 lg:w-[260px] lg:max-h-[calc(640px-140px)] lg:border-b-0 lg:border-r lg:px-3">
                <div className="flex gap-2 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible">
                  {/* 部分失败提示 */}
                  {partialErrors.length > 0 && (
                    <div className="mb-2 min-w-[170px] rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-300/80 lg:min-w-0">
                      {partialErrors.length} 个榜单获取失败，点击刷新重试
                    </div>
                  )}
                  {boards.map((board) => {
                    const active = board.id === activeBoard?.id;
                    return (
                      <button
                        key={board.id}
                        type="button"
                        onClick={() => setActiveBoardId(board.id)}
                        className={`group min-w-[170px] rounded-2xl border px-4 py-3 text-left transition-all lg:min-w-0 ${
                          active
                            ? "border-[#ff8e5a]/60 bg-white/10 shadow-[0_10px_30px_rgba(217,78,40,0.18)]"
                            : "border-white/10 bg-white/[0.04] hover:border-white/20 hover:bg-white/[0.07]"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2">
                            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: board.accent }} />
                            <span className="text-sm font-semibold text-white">{board.title}</span>
                          </div>
                          <TrendingUp className={`h-4 w-4 ${active ? "text-[#ff8e5a]" : "text-white/35"}`} />
                        </div>
                        <div className="mt-2 text-xs text-white/45">
                          {board.entries.length} 条 · {formatBoardTime(board.updated_at)}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </aside>

              <section className="min-h-0 flex-1 px-4 pb-6 pt-4 sm:px-6">
                {loading && boards.length === 0 ? (
                  <div className="flex h-full items-center justify-center gap-3 text-white/55">
                    <Loader2 className="h-5 w-5 animate-spin" />
                    正在拉取热榜...
                  </div>
                ) : error && boards.length === 0 ? (
                  <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
                    <Flame className="h-8 w-8 text-[#ff8e5a]" />
                    <p className="text-base font-semibold text-white">热榜暂时没有拉回来</p>
                    <p className="max-w-md text-sm text-white/50">{error}</p>
                  </div>
                ) : activeBoard ? (
                  <div className="flex h-full flex-col">
                    <div className="mb-4 flex items-center justify-between gap-4">
                      <div>
                        <h3 className="text-xl font-bold text-white">{activeBoard.title}</h3>
                        <p className="mt-1 text-sm text-white/45">
                          来源：{formatBoardSourceLabel(activeBoard.source_url)}
                        </p>
                      </div>
                      <a
                        href={activeBoard.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/[0.05] px-4 py-2 text-sm font-semibold text-white/70 transition-all hover:border-white/25 hover:bg-white/[0.1]"
                      >
                        查看源站
                      </a>
                    </div>
                    <div ref={entriesRef} className="scrollbar-hide flex-1 overflow-y-auto pr-1">
                      <div className="space-y-3">
                        {activeBoard.entries.map((entry) => (
                          <a
                            key={`${activeBoard.id}-${entry.rank}-${entry.article_url}`}
                            href={entry.article_url}
                            target="_blank"
                            rel="noreferrer"
                            className="group block rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-4 transition-all hover:border-white/20 hover:bg-white/[0.08]"
                          >
                            <div className="flex items-start gap-4">
                              <div
                                className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl text-sm font-bold text-white"
                                style={{
                                  background:
                                    entry.rank <= 3
                                      ? "linear-gradient(135deg, rgba(255,142,90,0.95), rgba(217,78,40,0.95))"
                                      : "rgba(255,255,255,0.08)",
                                }}
                              >
                                {entry.rank}
                              </div>
                              <div className="min-w-0 flex-1">
                                <div className="text-base font-semibold leading-7 text-white transition-colors group-hover:text-[#ffd3c4]">
                                  {entry.title}
                                </div>
                                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-white/45">
                                  {entry.score ? (
                                    <span className="rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-1">
                                      {entry.score}
                                    </span>
                                  ) : null}
                                  <span>{entry.source}</span>
                                </div>
                              </div>
                            </div>
                          </a>
                        ))}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="flex h-full items-center justify-center text-white/55">暂无热榜数据</div>
                )}
              </section>
            </div>
          </div>
        </div>
      </div>

      {/* ── SVG 连续链条（无装饰点） ── */}
      <svg
        className="fixed inset-0 z-[65] pointer-events-none"
        width={pageWidth}
        height={pageHeight}
        style={{ overflow: "visible" }}
      >
        <defs>
          <linearGradient id="chain-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgba(249,227,212,0.96)" />
            <stop offset="50%" stopColor="rgba(222,176,143,0.98)" />
            <stop offset="100%" stopColor="rgba(138,96,67,0.98)" />
          </linearGradient>
          <filter id="chain-shadow">
            <feDropShadow dx="0" dy="0" stdDeviation="1.5" floodColor="rgba(255,255,255,0.1)" />
          </filter>
        </defs>

        {/* 连续链条线条 */}
        <path
          d={`M ${anchorX} ${anchorY} Q ${midX} ${midY} ${handleX} ${handleY}`}
          fill="none"
          stroke="url(#chain-grad)"
          strokeWidth={clamp(4 + stretchRatio * 1.5, 4, 7)}
          strokeLinecap="round"
          filter="url(#chain-shadow)"
          opacity={chainOpacity}
        />
      </svg>

      {/* ── 链头按钮 ── */}
      <button
        type="button"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        className={`fixed z-[70] cursor-grab active:cursor-grabbing select-none ${
          isDragging ? "" : "transition-all duration-500"
        }`}
        style={{
          top: handleY,
          left: handleX,
          width: HANDLE_SIZE,
          height: HANDLE_SIZE,
          transform: "translate(-50%, -50%)",
          transitionTimingFunction: isDragging ? undefined : "cubic-bezier(0.34, 1.56, 0.64, 1)",
        }}
        aria-label="拖动链条打开热搜"
      >
        <div
          className="rounded-full border border-[#ffd8c5]/60 bg-[linear-gradient(180deg,rgba(255,238,228,0.95),rgba(248,210,189,0.95))] shadow-[0_8px_24px_rgba(0,0,0,0.22)]"
          style={{ width: HANDLE_SIZE, height: HANDLE_SIZE }}
        >
          <div className="absolute inset-[6px] rounded-full bg-[linear-gradient(180deg,rgba(251,244,239,0.98),rgba(243,221,205,0.98))]" />
          <div className="absolute inset-0 flex items-center justify-center text-[10px] font-bold tracking-[0.12em] text-[#8d4c31]">
            {loading ? "..." : "热搜"}
          </div>
        </div>
      </button>
    </>
  );
}
