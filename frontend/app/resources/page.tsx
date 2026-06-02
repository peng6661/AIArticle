"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, Copy, Database, Edit3, ExternalLink, Plus, RefreshCw, Search, Trash2, X } from "lucide-react";
import Navbar from "@/components/navbar";
import VideoBackground from "@/components/video-background";
import { ResourceItem, ResourceItemPayload, ResourceNetdiskType, taskApi } from "@/lib/tasks-api";

const PAGE_SIZE = 20;

const emptyForm: ResourceItemPayload = {
  name: "",
  netdiskType: "",
  url: "",
  feishuTableName: "主表",
  createdAt: "",
  updatedAt: "",
};

export default function ResourcesPage() {
  // ── 数据状态 ──────────────────────────────────────────────
  const [items, setItems] = useState<ResourceItem[]>([]);
  const [types, setTypes] = useState<ResourceNetdiskType[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  // ── 搜索状态 ──────────────────────────────────────────────
  const [keyword, setKeyword] = useState("");
  const [netdiskType, setNetdiskType] = useState("");
  // 提交时快照，避免边输边请求
  const [submittedKeyword, setSubmittedKeyword] = useState("");
  const [submittedNetdiskType, setSubmittedNetdiskType] = useState("");

  // ── 表单 & modal ──────────────────────────────────────────
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<ResourceItemPayload>(emptyForm);

  // ── 滚动回顶按钮 ──────────────────────────────────────────
  const [showScrollTop, setShowScrollTop] = useState(false);

  // ── Infinite scroll sentinel ──────────────────────────────
  const sentinelRef = useRef<HTMLDivElement>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);

  // ── 监听滚动显示"回顶"按钮 ───────────────────────────────
  useEffect(() => {
    const onScroll = () => setShowScrollTop(window.scrollY > 400);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const scrollToTop = () => window.scrollTo({ top: 0, behavior: "smooth" });

  // ── 初始化：加载网盘类型 ──────────────────────────────────
  useEffect(() => {
    taskApi.listResourceNetdiskTypes().then((res) => {
      if (res.success) setTypes(res.data);
    }).catch(() => {});
  }, []);

  // ── 首屏 / 搜索重置加载（第1页）─────────────────────────
  const loadFirstPage = useCallback(async (kw: string, ndt: string) => {
    setLoading(true);
    setError("");
    setItems([]);
    setPage(1);
    setHasMore(true);
    try {
      const res = await taskApi.listResourceItems({ keyword: kw, netdiskType: ndt, page: 1, pageSize: PAGE_SIZE });
      setItems(res.data);
      setTotal(res.pagination.total);
      setHasMore(res.data.length === PAGE_SIZE && res.pagination.total > PAGE_SIZE);
    } catch (err: any) {
      setError(err.response?.data?.detail || "资料加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  // ── 追加加载（第2页起）────────────────────────────────────
  const loadNextPage = useCallback(async (nextPage: number, kw: string, ndt: string) => {
    if (loadingMore) return;
    setLoadingMore(true);
    try {
      const res = await taskApi.listResourceItems({ keyword: kw, netdiskType: ndt, page: nextPage, pageSize: PAGE_SIZE });
      setItems((prev) => [...prev, ...res.data]);
      setPage(nextPage);
      setHasMore(res.data.length === PAGE_SIZE && res.pagination.total > nextPage * PAGE_SIZE);
    } catch {
      // 静默失败，保留现有数据
    } finally {
      setLoadingMore(false);
    }
  }, [loadingMore]);

  // ── 初始加载 ──────────────────────────────────────────────
  useEffect(() => {
    loadFirstPage("", "");
  }, []);// eslint-disable-line react-hooks/exhaustive-deps

  // ── IntersectionObserver：到底部自动加载 ─────────────────
  useEffect(() => {
    if (observerRef.current) observerRef.current.disconnect();

    observerRef.current = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loading && !loadingMore) {
          loadNextPage(page + 1, submittedKeyword, submittedNetdiskType);
        }
      },
      { rootMargin: "200px" }
    );

    if (sentinelRef.current) observerRef.current.observe(sentinelRef.current);

    return () => observerRef.current?.disconnect();
  }, [hasMore, loading, loadingMore, page, submittedKeyword, submittedNetdiskType, loadNextPage]);

  // ── 提交搜索 ──────────────────────────────────────────────
  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    setSubmittedKeyword(keyword);
    setSubmittedNetdiskType(netdiskType);
    loadFirstPage(keyword, netdiskType);
  };

  // ── 刷新 ──────────────────────────────────────────────────
  const handleRefresh = () => {
    loadFirstPage(submittedKeyword, submittedNetdiskType);
    taskApi.listResourceNetdiskTypes().then((res) => {
      if (res.success) setTypes(res.data);
    }).catch(() => {});
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
      feishuTableName: item.feishuTableName,
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
      loadFirstPage(submittedKeyword, submittedNetdiskType);
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
      loadFirstPage(submittedKeyword, submittedNetdiskType);
      taskApi.listResourceNetdiskTypes().then((res) => { if (res.success) setTypes(res.data); }).catch(() => {});
    } catch (err: any) {
      setError(err.response?.data?.detail || "删除失败");
    }
  };

  const copyUrl = async (url: string) => {
    await navigator.clipboard.writeText(url);
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
          <button
            onClick={openCreate}
            className="btn-brand inline-flex items-center justify-center gap-2 !px-6 !py-3 text-sm font-bold"
          >
            <Plus className="h-4 w-4" />
            新增资料
          </button>
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
              placeholder="搜索名称、链接或飞书表名…"
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
            <span className="text-sm text-white/50">
              {loading ? "加载中…" : total > 0 ? `已加载 ${items.length} / ${total} 条` : "暂无数据"}
            </span>
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
                  <th className="px-6 py-4 w-16">ID</th>
                  <th className="px-6 py-4">资料名称</th>
                  <th className="px-6 py-4 w-32">网盘类型</th>
                  <th className="px-6 py-4 w-28">飞书表</th>
                  <th className="px-6 py-4 w-40">更新时间</th>
                  <th className="px-6 py-4 w-36 text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.06]">
                {/* 首次加载骨架屏 */}
                {loading && items.length === 0 &&
                  Array.from({ length: 8 }).map((_, i) => (
                    <tr key={`sk-${i}`} className="animate-pulse">
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
                    className="group transition-colors duration-150 hover:bg-white/[0.04]"
                  >
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

                    <td className="px-6 py-4 text-white/55 whitespace-nowrap">
                      {item.feishuTableName || "—"}
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
                label="飞书表名"
                value={form.feishuTableName}
                onChange={(v) => setForm({ ...form, feishuTableName: v })}
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

// ── Field 表单项组件 ─────────────────────────────────────────
function Field(props: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  required?: boolean;
  className?: string;
}) {
  return (
    <label className={props.className}>
      <span className="mb-1.5 block text-xs font-bold text-white/40">{props.label}</span>
      <input
        required={props.required}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        placeholder={props.placeholder}
        className="h-11 w-full rounded-xl border border-white/10 bg-white/5 px-4 text-sm text-white outline-none transition placeholder:text-white/20 focus:border-[#D94E28]/60 focus:bg-white/8"
      />
    </label>
  );
}
