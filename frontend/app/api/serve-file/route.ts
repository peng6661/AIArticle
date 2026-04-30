import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const path = searchParams.get("path");

  if (!path) {
    return NextResponse.json({ error: "缺少 path 参数" }, { status: 400 });
  }

  try {
    const backendUrl = `${API_BASE}/api/serve-file?path=${encodeURIComponent(path)}`;
    const response = await fetch(backendUrl);

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "请求失败" }));
      return NextResponse.json(error, { status: response.status });
    }

    // ── 流式透传 ──────────────────────────────────────────────────
    // 不用 arrayBuffer()，直接把后端响应 body 作为 ReadableStream 转发给浏览器
    // 这样浏览器能实时收到分块数据，前端 reader.read() 才能持续更新进度
    const contentType = response.headers.get("content-type") || "application/octet-stream";
    const contentLength = response.headers.get("content-length");

    const headers: Record<string, string> = {
      "Content-Type": contentType,
      "Cache-Control": "public, max-age=3600",
      // 允许前端 JS 读取这两个 header（CORS 跨域场景需要）
      "Access-Control-Expose-Headers": "Content-Length, Content-Disposition",
    };

    if (contentLength) {
      headers["Content-Length"] = contentLength;
    }

    // 提取文件名，附加 Content-Disposition 供浏览器 a.download 使用
    const backendDisposition = response.headers.get("content-disposition");
    if (backendDisposition) {
      headers["Content-Disposition"] = backendDisposition;
    }

    return new NextResponse(response.body, {
      status: 200,
      headers,
    });
    // ─────────────────────────────────────────────────────────────
  } catch (error) {
    console.error("serve-file proxy error:", error);
    return NextResponse.json({ error: "后端服务不可用" }, { status: 502 });
  }
}
