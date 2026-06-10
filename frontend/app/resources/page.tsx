"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { ArrowDownUp, ArrowUp, ArrowUpDown, Copy, Database, Download, Edit3, ExternalLink, Plus, RefreshCw, Search, Trash2, Upload, X } from "lucide-react";
import Navbar from "@/components/navbar";
import VideoBackground from "@/components/video-background";
import { ResourceItem, ResourceItemPayload, ResourceNetdiskType, taskApi } from "@/lib/tasks-api";

const emptyForm: ResourceItemPayload = {
  name: "",
  netdiskType: "",
  url: "",
  createdAt: "",
  updatedAt: "",
};

export default function ResourcesPage() {
  // ── 数据状态 ──────────────────────────────────────────────
  const [items, setItems] = useState<ResourceItem[]>([]);
  const [types, setTypes] = useState<ResourceNetdiskType[]>([]);
  const [total, setTotal] = useState(0);
  const [pageSize, setPageSize] = useState(20);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  // ── 勾选状态 ──────────────────────────────────────────────
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  // 计算是否全选（当前页可见项全部选中）
  const isAllSelected = items.length > 0 && items.every((item) => selectedIds.has(item.id));

  // ── 搜索状态 ──────────────────────────────────────────────
  const [keyword, setKeyword] = useState("");
  const [netdiskType, setNetdiskType] = useState("");
  // 提交时快照，避免边输边请求
  const [submittedKeyword, setSubmittedKeyword] = useState("");
  const [submittedNetdiskType, setSubmittedNetdiskType] = useState("");

  // ── 排序状态 ──────────────────────────────────────────────
  const [sortBy, setSortBy] = useState<"id" | "updatedAt" | "createdAt">("updatedAt");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");

  // ── 表单 & modal ──────────────────────────────────────────
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<ResourceItemPayload>(emptyForm);

  // ── 滚动回顶按钮 ──────────────────────────────────────────
  const [showScrollTop, setShowScrollTop] = useState(false);

  // ── 导入/导出状态 ──────────────────────────────────────────
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{
    imported: number;
    duplicates: number;
    errors: number;
    dup_urls: string[];
    error_msgs: string[];
  } | null>(null);

  const [exportingFormat, setExportingFormat] = useState<string | null>(null);
  const [exportDropdownOpen, setExportDropdownOpen] = useState(false);
  const exportDropdownRef = useRef<HTMLDivElement>(null);

  // ── Infinite scroll sentinel ──────────────────────────────
  const sentinelRef = useRef<HTMLDivElement>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);

  // ── 监听滚动显示"回顶"按钮 ───────────────────────────────
  useEffect(() => {
    const onScroll = () => setShowScrollTop(window.scrollY > 400);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // ── 点击外部关闭导出下拉框 ──────────────────────────────
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (exportDropdownRef.current && !exportDropdownRef.current.contains(e.target as Node)) {
        setExportDropdownOpen(false);
      }
    };
    if (exportDropdownOpen) document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [exportDropdownOpen]);

  const scrollToTop = () => window.scrollTo({ top: 0, behavior: "smooth" });

  // ── 初始化：加载网盘类型 ──────────────────────────────────
  useEffect(() => {
    taskApi.listResourceNetdiskTypes().then((res) => {
      if (res.success) setTypes(res.data);
    }).catch(() => {});
  }, []);

  // ── 首屏 / 搜索重置加载（第1页）─────────────────────────
  const loadFirstPage = useCallback(async (kw: string, ndt: string, ps: number, sb: string, so: string) => {
    setLoading(true);
    setError("");
    setItems([]);
    setSelectedIds(new Set());
    setPage(1);
    setHasMore(true);
    try {
      const res = await taskApi.listResourceItems({ keyword: kw, netdiskType: ndt, page: 1, pageSize: ps, sortBy: sb, sortOrder: so });
      setItems(res.data);
      setTotal(res.pagination.total);
      setHasMore(res.data.length === ps && res.pagination.total > ps);
    } catch (err: any) {
      setError(err.response?.data?.detail || "资料加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  // ── 追加加载（第2页起）────────────────────────────────────
  const loadNextPage = useCallback(async (nextPage: number, kw: string, ndt: string, ps: number, sb: string, so: string) => {
    if (loadingMore) return;
    setLoadingMore(true);
    try {
      const res = await taskApi.listResourceItems({ keyword: kw, netdiskType: ndt, page: nextPage, pageSize: ps, sortBy: sb, sortOrder: so });
      setItems((prev) => [...prev, ...res.data]);
      setPage(nextPage);
      setHasMore(res.data.length === ps && res.pagination.total > nextPage * ps);
    } catch {
      // 静默失败，保留现有数据
    } finally {
      setLoadingMore(false);
    }
  }, [loadingMore]);

  // ── 初始加载 ──────────────────────────────────────────────
  useEffect(() => {
    loadFirstPage("", "", pageSize, sortBy, sortOrder);
  }, []);// eslint-disable-line react-hooks/exhaustive-deps

  // ── IntersectionObserver：到底部自动加载 ─────────────────
  useEffect(() => {
    if (observerRef.current) observerRef.current.disconnect();

    observerRef.current = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loading && !loadingMore) {
          loadNextPage(page + 1, submittedKeyword, submittedNetdiskType, pageSize, sortBy, sortOrder);
        }
      },
      { rootMargin: "200px" }
    );

    if (sentinelRef.current) observerRef.current.observe(sentinelRef.current);

    return () => observerRef.current?.disconnect();
  }, [hasMore, loading, loadingMore, page, submittedKeyword, submittedNetdiskType, sortBy, sortOrder, loadNextPage, pageSize]);

  // ── 提交搜索 ──────────────────────────────────────────────
  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    setSubmittedKeyword(keyword);
    setSubmittedNetdiskType(netdiskType);
    loadFirstPage(keyword, netdiskType, pageSize, sortBy, sortOrder);
  };

  // ── 刷新 ──────────────────────────────────────────────────
  const handleRefresh = () => {
    loadFirstPage(submittedKeyword, submittedNetdiskType, pageSize, sortBy, sortOrder);
    taskApi.listResourceNetdiskTypes().then((res) => {
      if (res.success) setTypes(res.data);
    }).catch(() => {});
  };

  // ── 直接导出（下拉框选中格式后触发）─────────────────────────
  const handleDirectExport = async (format: "excel" | "pdf" | "word") => {
    if (selectedIds.size === 0) {
      setError("请先勾选需要导出的资料");
      setTimeout(() => setError(""), 3000);
      return;
    }
    setExportingFormat(format);
    setExportDropdownOpen(false);
    setError("");
    try {
      const blob = await taskApi.exportResources({
        ids: Array.from(selectedIds),
        format,
      });
      const ext = format === "pdf" ? "pdf" : format === "word" ? "docx" : "xlsx";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `资料库导出.${ext}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err: any) {
      setError(err.response?.data?.detail || "导出失败");
    } finally {
      setExportingFormat(null);
    }
  };

  // ── Modal 操作 ────────────────────────────────────────────
  const openCreate = () => {
    setEditingId(null);
    setForm(emptyForm);
    setModalOpen(true);
  };

  const openEdit = (item: ResourceItem) => {
    setEditingId(item.id);
    setForm({
      name: item.name,
      netdiskType: item.netdiskType,
      url: item.url,
      createdAt: item.createdAt,
      updatedAt: item.updatedAt,
    });
    setModalOpen(true);
  };

  const saveItem = async (event: FormEvent) => {
    event.preventDefault();
    if (!form.name.trim() || !form.url.trim()) return;
    setSaving(true);
    setError("");
    try {
      if (editingId) {
        await taskApi.updateResourceItem(editingId, form);
      } else {
        await taskApi.createResourceItem(form);
      }
      setModalOpen(false);
      loadFirstPage(submittedKeyword, submittedNetdiskType, pageSize, sortBy, sortOrder);
      taskApi.listResourceNetdiskTypes().then((res) => { if (res.success) setTypes(res.data); }).catch(() => {});
    } catch (err: any) {
      setError(err.response?.data?.detail || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const deleteItem = async (item: ResourceItem) => {
    if (!confirm(`确定删除「${item.name}」吗？`)) return;
    try {
      await taskApi.deleteResourceItem(item.id);
      loadFirstPage(submittedKeyword, submittedNetdiskType, pageSize, sortBy, sortOrder);
      taskApi.listResourceNetdiskTypes().then((res) => { if (res.success) setTypes(res.data); }).catch(() => {});
    } catch (err: any) {
      setError(err.response?.data?.detail || "删除失败");
    }
  };

  const copyUrl = async (url: string) => {
    await navigator.clipboard.writeText(url);
  };

  // ── 导入 Excel ────────────────────────────────────────────
  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.endsWith(".xlsx") && !file.name.endsWith(".xls")) {
      setError("仅支持 .xlsx / .xls 文件");
      return;
    }
    setImporting(true);
    setImportResult(null);
    setError("");
    try {
      const res = await taskApi.importResources(file);
      setImportResult(res.data);
      loadFirstPage(submittedKeyword, submittedNetdiskType, pageSize, sortBy, sortOrder);
      taskApi.listResourceNetdiskTypes().then((r) => { if (r.success) setTypes(r.data); }).catch(() => {});
    } catch (err: any) {
      setError(err.response?.data?.detail || "导入失败");
    } finally {
      setImporting(false);
      // 清空 input 以便重复选择同一文件
      e.target.value = "";
    }
  };


  // ── 勾选操作 ──────────────────────────────────────────────
  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (isAllSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map((item) => item.id)));
    }
  };

  // ── 数量筛选切换 ──────────────────────────────────────────
  const [pageSizeInput, setPageSizeInput] = useState("20");
  const handlePageSizeBlur = () => {
    const raw = pageSizeInput.trim();
    const num = parseInt(raw, 10);
    if (isNaN(num) || num < 1) {
      setPageSizeInput(String(pageSize));
      return;
    }
    const clamped = Math.min(num, 200);
    if (clamped === pageSize) {
      setPageSizeInput(String(clamped));
      return;
    }
    setPageSize(clamped);
    setPageSizeInput(String(clamped));
    loadFirstPage(submittedKeyword, submittedNetdiskType, clamped, sortBy, sortOrder);
  };
  const handlePageSizeKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") handlePageSizeBlur();
  };

  // ─────────────────────────────────────────────────────────
  return (
    <main className="relative min-h-screen text-white">
      <Navbar />
      <VideoBackground />

      {/* ── 主体内容区（80% 宽度居中）────────────────────── */}
      <section className="relative z-10 mx-auto w-[80%] pb-20 pt-24">

        {/* ── 页头：标题 + 新增按钮 ── */}
        <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex items-center gap-4">
            <div>
              <p className="text-xs font-bold uppercase tracking-widest text-[#FF8A65]/80">Resource Library</p>
              <h1 className="mt-0.5 text-4xl font-black tracking-tight">资料库</h1>
              <p className="mt-1 text-sm text-white/50">
                {total > 0 ? `共 ${total} 条网盘资料，统一检索与归档` : "网盘资料统一检索、维护与归档"}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {/* 导入按钮 */}
            <label className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-5 py-3 text-sm font-bold text-white/70 transition hover:border-[#D94E28]/40 hover:bg-[#D94E28]/10 hover:text-[#FF8A65] active:scale-95">
              <Upload className="h-4 w-4" />
              {importing ? "导入中…" : "导入"}
              <input
                type="file"
                accept=".xlsx,.xls"
                onChange={handleImport}
                disabled={importing}
                className="hidden"
              />
            </label>

            {/* 导出下拉框 */}
            <div className="relative" ref={exportDropdownRef}>
              <button
                onClick={() => setExportDropdownOpen(!exportDropdownOpen)}
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-5 py-3 text-sm font-bold text-white/70 transition hover:border-[#D94E28]/40 hover:bg-[#D94E28]/10 hover:text-[#FF8A65] active:scale-95"
              >
                <Download className="h-4 w-4" />
                {exportingFormat ? "导出中…" : "导出"}
              </button>
              {exportDropdownOpen && (
                <div className="absolute right-0 top-full mt-2 z-50 min-w-[180px] overflow-hidden rounded-xl border border-white/10 bg-[#111] backdrop-blur-xl shadow-2xl">
                  {(["excel", "pdf", "word"] as const).map((fmt) => {
                    const labels: Record<string, string> = { excel: "Excel (.xlsx)", pdf: "PDF (.pdf)", word: "Word (.docx)" };
                    const isLoading = exportingFormat === fmt;
                    return (
                      <button
                        key={fmt}
                        onClick={() => { if (!isLoading) handleDirectExport(fmt); }}
                        disabled={isLoading}
                        className="flex w-full items-center gap-3 px-4 py-3 text-sm font-bold text-white/70 transition hover:bg-[#D94E28]/10 hover:text-[#FF8A65] disabled:opacity-40"
                      >
                        {isLoading ? (
                          <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
                        ) : (
                          <Download className="h-4 w-4" />
                        )}
                        {labels[fmt]}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {/* 新增按钮 */}
            <button
              onClick={openCreate}
              className="btn-brand inline-flex items-center justify-center gap-2 !px-6 !py-3 text-sm font-bold"
            >
              <Plus className="h-4 w-4" />
              新增资料
            </button>
          </div>
        </div>

        {/* ── 搜索栏 ── */}
        <form
          onSubmit={submitSearch}
          className="mb-6 flex flex-wrap items-center gap-3 rounded-2xl border border-white/10 bg-black/40 p-5 backdrop-blur-xl"
        >
          {/* 关键词搜索 */}
          <div className="relative min-w-[240px] flex-1">
            <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-white/35" />
            <input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              className="h-12 w-full rounded-xl border border-white/10 bg-white/5 pl-11 pr-4 text-sm text-white outline-none transition placeholder:text-white/30 focus:border-[#D94E28]/60 focus:bg-white/8"
              placeholder="搜索名称或链接…"
            />
          </div>

          {/* 网盘类型筛选 */}
          <select
            value={netdiskType}
            onChange={(e) => {
              setNetdiskType(e.target.value);
            }}
            className="h-12 min-w-[160px] rounded-xl border border-white/10 bg-[#111]/80 px-4 text-sm text-white outline-none transition focus:border-[#D94E28]/60"
          >
            <option value="">全部网盘</option>
            {types.map((t) => (
              <option key={t.name} value={t.name}>
                {t.name} ({t.count})
              </option>
            ))}
          </select>

          {/* 数量筛选 */}
          <div className="relative min-w-[100px]">
            <input
              type="number"
              min={1}
              max={200}
              value={pageSizeInput}
              onChange={(e) => setPageSizeInput(e.target.value)}
              onBlur={handlePageSizeBlur}
              onKeyDown={handlePageSizeKeyDown}
              className="h-12 w-full rounded-xl border border-white/10 bg-[#111]/80 pl-4 pr-3 text-sm text-white outline-none transition placeholder:text-white/30 focus:border-[#D94E28]/60"
              placeholder="条/页"
            />
          </div>

          {/* 排序控件 */}
          <div className="flex items-center gap-1">
            <select
              value={sortBy}
              onChange={(e) => {
                const newSortBy = e.target.value as "id" | "updatedAt" | "createdAt";
                setSortBy(newSortBy);
                loadFirstPage(submittedKeyword, submittedNetdiskType, pageSize, newSortBy, sortOrder);
              }}
              className="h-12 min-w-[110px] rounded-xl border border-white/10 bg-[#111]/80 px-4 text-sm text-white outline-none transition focus:border-[#D94E28]/60"
            >
              <option value="updatedAt">更新时间</option>
              <option value="createdAt">创建时间</option>
              <option value="id">ID</option>
            </select>
            <button
              type="button"
              onClick={() => {
                const newOrder = sortOrder === "desc" ? "asc" : "desc";
                setSortOrder(newOrder);
                loadFirstPage(submittedKeyword, submittedNetdiskType, pageSize, sortBy, newOrder);
              }}
              className="inline-flex h-12 w-12 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-white/60 transition hover:border-[#D94E28]/40 hover:bg-[#D94E28]/10 hover:text-[#FF8A65] active:scale-95"
              title={sortOrder === "desc" ? "当前：降序 → 切换升序" : "当前：升序 → 切换降序"}
            >
              {sortOrder === "desc" ? <ArrowDownUp className="h-4 w-4" /> : <ArrowUpDown className="h-4 w-4" />}
            </button>
          </div>

          {/* 查询按钮 */}
          <button
            type="submit"
            className="h-12 rounded-xl border border-[#D94E28]/50 bg-[#D94E28]/15 px-6 text-sm font-bold text-[#FF8A65] transition hover:bg-[#D94E28]/28 active:scale-95"
          >
            查询
          </button>

          {/* 刷新按钮 */}
          <button
            type="button"
            onClick={handleRefresh}
            className="inline-flex h-12 items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-5 text-sm font-bold text-white/70 transition hover:bg-white/10 active:scale-95"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            刷新
          </button>
        </form>

        {/* ── 错误提示 ── */}
        {error && (
          <div className="mb-4 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {error}
          </div>
        )}

        {/* ── 数据表格容器 ── */}
        <div className="overflow-hidden rounded-2xl border border-white/10 bg-black/40 backdrop-blur-xl">

          {/* 表头信息栏 */}
          <div className="flex items-center justify-between border-b border-white/8 px-6 py-4">
            <div className="flex items-center gap-3">
              <span className="text-sm text-white/50">
                {loading ? "加载中…" : total > 0 ? `已加载 ${items.length} / ${total} 条` : "暂无数据"}
              </span>
              {selectedIds.size > 0 && (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-[#D94E28]/25 bg-[#D94E28]/10 px-3 py-0.5 text-xs font-bold text-[#FF8A65]">
                  已选 {selectedIds.size} 项
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-[#D94E28]/60" />
              <span className="text-xs font-semibold text-white/40 uppercase tracking-wider">Live</span>
            </div>
          </div>

          {/* 表格 */}
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-white/8 bg-white/[0.03] text-xs font-bold uppercase tracking-wider text-white/40">
                <tr>
                  <th className="px-6 py-4 w-10">
                    <input
                      type="checkbox"
                      checked={isAllSelected}
                      onChange={toggleSelectAll}
                      className="h-4 w-4 cursor-pointer accent-[#D94E28]"
                    />
                  </th>
                  <th className="px-6 py-4 w-16">ID</th>
                  <th className="px-6 py-4">资料名称</th>
                  <th className="px-6 py-4 w-32">网盘类型</th>
                  <th className="px-6 py-4 w-40">更新时间</th>
                  <th className="px-6 py-4 w-36 text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.06]">
                {/* 首次加载骨架屏 */}
                {loading && items.length === 0 &&
                  Array.from({ length: 8 }).map((_, i) => (
                    <tr key={`sk-${i}`} className="animate-pulse">
                      <td className="px-6 py-4"><div className="h-4 w-4 rounded bg-white/10" /></td>
                      <td className="px-6 py-4"><div className="h-4 w-8 rounded bg-white/10" /></td>
                      <td className="px-6 py-4">
                        <div className="h-4 w-64 rounded bg-white/10 mb-2" />
                        <div className="h-3 w-40 rounded bg-white/6" />
                      </td>
                      <td className="px-6 py-4"><div className="h-6 w-20 rounded-full bg-white/10" /></td>
                      <td className="px-6 py-4"><div className="h-4 w-16 rounded bg-white/10" /></td>
                      <td className="px-6 py-4"><div className="h-4 w-28 rounded bg-white/10" /></td>
                      <td className="px-6 py-4"><div className="h-8 w-28 rounded-lg bg-white/10 ml-auto" /></td>
                    </tr>
                  ))
                }

                {/* 实际数据行 */}
                {items.map((item) => (
                  <tr
                    key={item.id}
                    className={`group transition-colors duration-150 hover:bg-white/[0.04] ${selectedIds.has(item.id) ? "bg-[#D94E28]/6" : ""}`}
                  >
                    <td className="px-6 py-4">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(item.id)}
                        onChange={() => toggleSelect(item.id)}
                        className="h-4 w-4 cursor-pointer accent-[#D94E28]"
                      />
                    </td>
                    <td className="px-6 py-4 text-white/35 tabular-nums">{item.id}</td>

                    <td className="px-6 py-4 max-w-0 w-full">
                      <div className="flex flex-col gap-1">
                        <span
                          className="truncate font-semibold text-white/90 group-hover:text-white transition-colors"
                          title={item.name}
                        >
                          {item.name}
                        </span>
                        <span
                          className="truncate text-xs text-white/30 font-mono"
                          title={item.url}
                        >
                          {item.url}
                        </span>
                      </div>
                    </td>

                    <td className="px-6 py-4">
                      <span className="inline-block rounded-full border border-[#D94E28]/25 bg-[#D94E28]/10 px-3 py-1 text-xs font-bold text-[#FF8A65] whitespace-nowrap">
                        {item.netdiskType || "未分类"}
                      </span>
                    </td>

                    <td className="px-6 py-4 text-white/45 text-xs whitespace-nowrap tabular-nums">
                      {item.updatedAt || item.createdAt || "—"}
                    </td>

                    <td className="px-6 py-4">
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          title="复制链接"
                          onClick={() => copyUrl(item.url)}
                          className="rounded-lg border border-white/10 bg-white/[0.04] p-2 text-white/50 transition hover:border-white/20 hover:text-white"
                        >
                          <Copy className="h-3.5 w-3.5" />
                        </button>
                        <a
                          title="打开链接"
                          href={item.url}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded-lg border border-white/10 bg-white/[0.04] p-2 text-white/50 transition hover:border-white/20 hover:text-white"
                        >
                          <ExternalLink className="h-3.5 w-3.5" />
                        </a>
                        <button
                          title="编辑"
                          onClick={() => openEdit(item)}
                          className="rounded-lg border border-white/10 bg-white/[0.04] p-2 text-white/50 transition hover:border-[#D94E28]/40 hover:text-[#FF8A65]"
                        >
                          <Edit3 className="h-3.5 w-3.5" />
                        </button>
                        <button
                          title="删除"
                          onClick={() => deleteItem(item)}
                          className="rounded-lg border border-red-500/15 bg-red-500/8 p-2 text-red-300/60 transition hover:bg-red-500/20 hover:text-red-200"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}

                {/* 空状态 */}
                {!loading && items.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-6 py-20 text-center">
                      <div className="flex flex-col items-center gap-3 text-white/35">
                        <Database className="h-10 w-10 opacity-30" />
                        <span className="text-sm">暂无资料，点击右上角「新增资料」开始添加</span>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* 底部加载更多区域 */}
          {(hasMore || loadingMore) && (
            <div ref={sentinelRef} className="flex items-center justify-center gap-2 border-t border-white/8 px-6 py-5 text-sm text-white/40">
              {loadingMore ? (
                <>
                  <RefreshCw className="h-4 w-4 animate-spin text-[#FF8A65]/60" />
                  <span>加载更多…</span>
                </>
              ) : (
                <span className="h-1" />/* sentinel 占位 */
              )}
            </div>
          )}

          {/* 全部加载完毕 */}
          {!hasMore && !loading && items.length > 0 && (
            <div className="border-t border-white/8 px-6 py-4 text-center text-xs text-white/25">
              — 已加载全部 {total} 条资料 —
            </div>
          )}
        </div>
      </section>

      {/* ── 回顶按钮 ── */}
      <button
        onClick={scrollToTop}
        aria-label="回到顶部"
        className={`fixed bottom-8 right-8 z-50 flex h-16 w-16 items-center justify-center rounded-full border border-white/15 bg-black/60 text-white/70 shadow-xl backdrop-blur-md transition-all duration-300 hover:border-[#D94E28]/50 hover:bg-[#D94E28]/20 hover:text-[#FF8A65] hover:scale-110 active:scale-95 ${
          showScrollTop ? "translate-y-0 opacity-100" : "translate-y-4 opacity-0 pointer-events-none"
        }`}
      >
        <ArrowUp className="h-7 w-7" />
      </button>

      {/* ── 导入结果弹窗 ── */}
      {importResult && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#0d0d0d] p-6 shadow-2xl">
            <div className="mb-5 flex items-center justify-between">
              <h2 className="text-lg font-black">导入结果</h2>
              <button
                onClick={() => setImportResult(null)}
                className="rounded-xl border border-white/10 bg-white/5 p-2 text-white/60 transition hover:bg-white/10"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* 统计数字 */}
            <div className="mb-5 grid grid-cols-3 gap-4">
              <div className="rounded-xl border border-green-500/20 bg-green-500/10 p-4 text-center">
                <div className="text-3xl font-black text-green-400">{importResult.imported}</div>
                <div className="mt-1 text-xs text-green-300/70">成功导入</div>
              </div>
              <div className="rounded-xl border border-yellow-500/20 bg-yellow-500/10 p-4 text-center">
                <div className="text-3xl font-black text-yellow-400">{importResult.duplicates}</div>
                <div className="mt-1 text-xs text-yellow-300/70">重复跳过</div>
              </div>
              <div className="rounded-xl border border-red-500/20 bg-red-500/10 p-4 text-center">
                <div className="text-3xl font-black text-red-400">{importResult.errors}</div>
                <div className="mt-1 text-xs text-red-300/70">格式错误</div>
              </div>
            </div>

            {/* 错误详情 */}
            {importResult.error_msgs.length > 0 && (
              <div className="mb-4">
                <p className="mb-2 text-xs font-bold text-white/40">错误详情：</p>
                <div className="max-h-32 overflow-auto rounded-lg border border-white/8 bg-white/[0.03] p-3 text-xs text-red-300/80">
                  {importResult.error_msgs.map((msg, i) => (
                    <div key={i}>{msg}</div>
                  ))}
                </div>
              </div>
            )}

            {/* 重复链接 */}
            {importResult.dup_urls.length > 0 && (
              <div className="mb-4">
                <p className="mb-2 text-xs font-bold text-white/40">重复链接（前 {importResult.dup_urls.length} 条）：</p>
                <div className="max-h-32 overflow-auto rounded-lg border border-white/8 bg-white/[0.03] p-3 text-xs text-yellow-300/70 font-mono">
                  {importResult.dup_urls.map((url, i) => (
                    <div key={i} className="truncate">{url}</div>
                  ))}
                </div>
              </div>
            )}

            <div className="flex justify-end">
              <button
                onClick={() => setImportResult(null)}
                className="btn-brand !px-6 !py-2.5 text-sm"
              >
                确认
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 新增/编辑 Modal ── */}
      {modalOpen && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <form
            onSubmit={saveItem}
            className="w-full max-w-2xl rounded-2xl border border-white/10 bg-[#0d0d0d] p-6 shadow-2xl"
          >
            <div className="mb-6 flex items-center justify-between">
              <h2 className="text-lg font-black">{editingId ? "编辑资料" : "新增资料"}</h2>
              <button
                type="button"
                onClick={() => setModalOpen(false)}
                className="rounded-xl border border-white/10 bg-white/5 p-2 text-white/60 transition hover:bg-white/10"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {error && (
              <div className="mb-4 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-200">
                {error}
              </div>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                label="资料名称"
                value={form.name}
                onChange={(v) => setForm({ ...form, name: v })}
                required
              />
              <Field
                label="网盘类型"
                value={form.netdiskType}
                onChange={(v) => setForm({ ...form, netdiskType: v })}
                types={types}
              />
              <Field
                label="创建时间"
                value={form.createdAt}
                onChange={(v) => setForm({ ...form, createdAt: v })}
                placeholder="YYYY-MM-DD HH:mm:ss"
              />
              <Field
                label="更新时间"
                value={form.updatedAt}
                onChange={(v) => setForm({ ...form, updatedAt: v })}
                placeholder="YYYY-MM-DD HH:mm:ss"
              />
              <Field
                label="网盘链接"
                value={form.url}
                onChange={(v) => setForm({ ...form, url: v })}
                required
                className="sm:col-span-2"
              />
            </div>

            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setModalOpen(false)}
                className="rounded-xl border border-white/10 bg-white/5 px-5 py-2.5 text-sm font-bold text-white/70 transition hover:bg-white/10"
              >
                取消
              </button>
              <button
                disabled={saving}
                className="btn-brand !px-6 !py-2.5 text-sm disabled:opacity-60"
              >
                {saving ? "保存中…" : "保存"}
              </button>
            </div>
          </form>
        </div>
      )}
    </main>
  );
}

// ── 自定义网盘类型下拉组件 ──────────────────────────────
function NetdiskTypeSelect(props: {
  value: string;
  onChange: (value: string) => void;
  types: { name: string; count: number }[];
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const selected = props.types.find((t) => t.name === props.value);

  return (
    <div ref={ref} className="relative">
      {/* 触发按钮 */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`h-11 w-full rounded-xl border px-4 text-sm text-left transition
          ${open ? "border-[#D94E28]/60 bg-white/8" : "border-white/10 bg-white/5 hover:border-white/20"}
          flex items-center justify-between gap-2`}
      >
        <span className={selected ? "text-white" : "text-white/30"}>
          {selected ? `${selected.name} (${selected.count})` : "请选择网盘类型"}
        </span>
        <svg
          width="16" height="16" viewBox="0 0 16 16" fill="none"
          className={`text-white/40 transition-transform ${open ? "rotate-180" : ""}`}
        >
          <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>

      {/* 下拉列表 */}
      {open && (
        <div className="absolute z-50 mt-1.5 w-full overflow-auto rounded-xl border border-white/10 bg-[#0e0e1a] py-1 shadow-2xl shadow-black/60 max-h-60">
          {props.types.map((t) => {
            const isActive = t.name === props.value;
            return (
              <button
                key={t.name}
                type="button"
                onClick={() => {
                  props.onChange(t.name);
                  setOpen(false);
                }}
                className={`w-full px-4 py-2.5 text-sm text-left transition
                  ${isActive ? "bg-[#D94E28]/15 text-[#D94E28] font-semibold" : "text-white/80 hover:bg-white/8"}
                  flex items-center justify-between gap-2`}
              >
                <span>{t.name} <span className="text-white/30 text-xs">({t.count})</span></span>
                {isActive && (
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="text-[#D94E28] shrink-0">
                    <path d="M3 8.5l3 3 7-7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Field 表单项组件 ─────────────────────────────────
function Field(props: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  required?: boolean;
  className?: string;
  types?: { name: string; count: number }[];
}) {
  const isSelect = !!(props.types && props.types.length > 0);

  return (
    <label className={props.className}>
      <span className="mb-1.5 block text-xs font-bold text-white/40">{props.label}</span>
      {isSelect ? (
        <NetdiskTypeSelect value={props.value} onChange={props.onChange} types={props.types!} />
      ) : (
        <input
          required={props.required}
          value={props.value}
          onChange={(e) => props.onChange(e.target.value)}
          placeholder={props.placeholder}
          className="h-11 w-full rounded-xl border border-white/10 bg-white/5 px-4 text-sm text-white outline-none transition placeholder:text-white/20 focus:border-[#D94E28]/60 focus:bg-white/8"
        />
      )}
    </label>
  );
}
