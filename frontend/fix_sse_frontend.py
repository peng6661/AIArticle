import sys
content = open(r'G:/python实战/AIArticle/frontend/app/download/page.tsx', encoding='utf-8').read()

# 改进1: 添加 started 事件处理，改进状态显示
old1 = '''      setDlState((prev) => ({
        ...prev,
        totalMB,
        statusText: totalMB > 0 ? "正在连接…" : "正在解析视频…",
      }));

      // 2. 启动 SSE 实时进度监听
      const ytEs = new EventSource(`${API_BASE}/youtube-progress?download_id=${downloadId}`);
      ytEventSourceRef.current = ytEs;

      ytEs.addEventListener("progress", (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data);
          const downloaded = data.downloaded || 0;
          const total = data.total || totalBytes;
          const progressPct = data.progress || 0;
          const speed = data.speed || 0;
          const downloadedMB = downloaded / 1048576;
          const totalMBVal = total / 1048576;

          setDlState((prev) => ({
            ...prev,
            progress: Math.min(Math.round(progressPct), 99),
            loadedMB: downloadedMB,
            totalMB: totalMBVal > 0 ? totalMBVal : prev.totalMB,
            speedKBs: speed > 0 ? Math.round(speed / 1024) : prev.speedKBs,
            statusText: total > 0
              ? `已下载 ${formatSize(downloadedMB)} / ${formatSize(totalMBVal)}`
              : `已下载 ${formatSize(downloadedMB)}…`,
          }));
        } catch {}
      });

      ytEs.addEventListener("done", () => {
        setDlState((prev) => ({ ...prev, progress: 100, statusText: "正在保存文件…" }));
        ytEs.close();
        ytEventSourceRef.current = null;
      });

      ytEs.addEventListener("error", (e: MessageEvent) => {
        console.warn("[!] YouTube SSE 进度错误:", e);
        ytEs.close();
        ytEventSourceRef.current = null;
      });'''

new1 = '''      setDlState((prev) => ({
        ...prev,
        totalMB,
        statusText: "准备开始下载…",
      }));

      // 2. 启动 SSE 实时进度监听
      const ytEs = new EventSource(`${API_BASE}/youtube-progress?download_id=${downloadId}`);
      ytEventSourceRef.current = ytEs;

      // ★★★ 改进：添加 started 事件处理 ★★★
      ytEs.addEventListener("started", (e: MessageEvent) => {
        console.log("[✓] YouTube下载已启动");
        setDlState((prev) => ({
          ...prev,
          statusText: "正在下载…",
        }));
      });

      ytEs.addEventListener("progress", (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data);
          const downloaded = data.downloaded || 0;
          const total = data.total || totalBytes;
          const progressPct = data.progress || 0;
          const speed = data.speed || 0;
          const downloadedMB = downloaded / 1048576;
          const totalMBVal = total / 1048576;

          setDlState((prev) => ({
            ...prev,
            progress: Math.min(Math.round(progressPct), 99),
            loadedMB: downloadedMB,
            totalMB: totalMBVal > 0 ? totalMBVal : prev.totalMB,
            speedKBs: speed > 0 ? Math.round(speed / 1024) : prev.speedKBs,
            statusText: total > 0
              ? `已下载 ${formatSize(downloadedMB)} / ${formatSize(totalMBVal)}`
              : `已下载 ${formatSize(downloadedMB)}…`,
          }));
        } catch {}
      });

      ytEs.addEventListener("done", () => {
        setDlState((prev) => ({ ...prev, progress: 100, statusText: "正在保存文件…" }));
        ytEs.close();
        ytEventSourceRef.current = null;
      });

      // ★★★ 改进：改进错误处理，添加重连逻辑 ★★★
      ytEs.addEventListener("error", (e: MessageEvent) => {
        // 只在没有关闭时才记录错误
        if (ytEs.readyState === EventSource.CLOSED) {
          return;
        }
        console.warn("[!] YouTube SSE 连接状态:", ytEs.readyState, e);
        // 连接错误，继续监听（EventSource会自动尝试重连）
      });'''

# 改进2: 改进下载开始后的状态显示
old2 = '''        // 优先使用响应头的 Content-Length（如果元数据没拿到）
        if (totalBytes === 0) {
          const cl = resp.headers.get("content-length");
          if (cl) {
            totalBytes = parseInt(cl, 10);
            totalMB = totalBytes / 1048576;
            setDlState((prev) => ({ ...prev, totalMB }));
          }
        }'''

new2 = '''        // ★★★ 改进：下载已开始，更新状态 ★★★
        setDlState((prev) => ({
          ...prev,
          statusText: "正在下载…",
        }));

        // 优先使用响应头的 Content-Length（如果元数据没拿到）
        if (totalBytes === 0) {
          const cl = resp.headers.get("content-length");
          if (cl) {
            totalBytes = parseInt(cl, 10);
            totalMB = totalBytes / 1048576;
            setDlState((prev) => ({ ...prev, totalMB }));
          }
        }'''

print('Found old1:', old1 in content)
print('Found old2:', old2 in content)

if old1 in content:
    content = content.replace(old1, new1)
    print('Replaced old1 successfully!')
else:
    print('old1 not found')

if old2 in content:
    content = content.replace(old2, new2)
    print('Replaced old2 successfully!')
else:
    print('old2 not found')

with open(r'G:/python实战/AIArticle/frontend/app/download/page.tsx', 'w', encoding='utf-8') as f:
    f.write(content)
print('Done!')
