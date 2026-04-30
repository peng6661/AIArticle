import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const path = searchParams.get("path");

  if (!path) {
    return NextResponse.json({ error: "缺少 path 参数" }, { status: 400 });
  }

  try {
    const backendUrl = `${API_BASE}/api/video-info?path=${encodeURIComponent(path)}`;
    const response = await fetch(backendUrl, {
      headers: { "Content-Type": "application/json" },
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "请求失败" }));
      return NextResponse.json(error, { status: response.status });
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error("video-info proxy error:", error);
    return NextResponse.json({ error: "后端服务不可用" }, { status: 502 });
  }
}
