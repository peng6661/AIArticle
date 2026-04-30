"""
图片生成服务 —— 异步并发版
1. asyncio 并发调用生图接口（SiliconFlow）
2. 并发下载图片到本地（绝对路径，UTF-8 安全文件名）
3. 并发上传到微信素材库，获取微信域 URL 和 media_id
返回 image_map: {"img_01": {"local_path": "...", "wechat_url": "...", "media_id": "..."}}
"""
from __future__ import annotations

import asyncio
import importlib
import mimetypes
import subprocess
import sys
import time
from pathlib import Path

from app.core.config import get_settings


def _ensure_openai():
    try:
        return importlib.import_module("openai")
    except ImportError:
        print("未检测到依赖 openai，正在自动安装...")
        subprocess.run([sys.executable, "-m", "pip", "install", "openai"], check=True)
        return importlib.import_module("openai")


def _ensure_httpx():
    try:
        return importlib.import_module("httpx")
    except ImportError:
        print("未检测到依赖 httpx，正在自动安装...")
        subprocess.run([sys.executable, "-m", "pip", "install", "httpx"], check=True)
        return importlib.import_module("httpx")


# ── 异步生图 + 下载单张图片 ───────────────────────────────────────────────────

async def _async_generate_one(
    prompt_item: dict,
    api_key: str,
    output_dir: Path,
    model_name: str,
    image_size: str,
    semaphore: asyncio.Semaphore,
) -> tuple[str, Path]:
    """
    生成单张图片并下载到本地。
    返回 (img_id, local_path)
    """
    httpx = _ensure_httpx()
    cfg = get_settings()

    img_id: str = prompt_item["id"]
    prompt: str = prompt_item["prompt"]

    async with semaphore:
        # ── 1. 调用生图接口（同步 SDK 包装到线程池）────────────────────────
        loop = asyncio.get_event_loop()

        def _call_image_api():
            openai_mod = _ensure_openai()
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=cfg.siliconflow_base_url)
            resp = client.images.generate(
                model=model_name,
                prompt=prompt,
                size=image_size,
                n=1,
            )
            url = None
            if hasattr(resp, "data") and resp.data:
                url = getattr(resp.data[0], "url", None)
            if not url and hasattr(resp, "model_dump"):
                data = resp.model_dump().get("data", [])
                if data:
                    url = data[0].get("url")
            if not url:
                raise ValueError(f"[{img_id}] 生图接口未返回 URL，prompt: {prompt[:60]}")
            return url

        image_url = await loop.run_in_executor(None, _call_image_api)

        # ── 2. 下载图片到本地（绝对路径，纯 ASCII 文件名避免 Windows 编码问题）
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_name = f"{img_id}_{timestamp}.png"
        local_path = (output_dir / safe_name).resolve()  # 强制绝对路径
        output_dir.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(timeout=60) as client_http:
            r = await client_http.get(image_url)
            r.raise_for_status()
            local_path.write_bytes(r.content)

        print(f"[+] 图片 {img_id} 已下载: {local_path}")
        return img_id, local_path


# ── 异步上传单张图片到微信素材库 ──────────────────────────────────────────────

async def _async_upload_to_wechat(
    img_id: str,
    local_path: Path,
    access_token: str,
    wechat_api_base: str,
    semaphore: asyncio.Semaphore,
) -> tuple[str, dict]:
    """
    将本地图片上传为微信永久素材（图文消息内的图片）。
    返回 (img_id, {"wechat_url": "...", "media_id": "..."})
    微信接口：POST /cgi-bin/material/add_material?type=image
    """
    httpx = _ensure_httpx()

    async with semaphore:
        mime_type = mimetypes.guess_type(local_path.name)[0] or "image/png"
        url = f"{wechat_api_base}/cgi-bin/material/add_material?access_token={access_token}&type=image"

        async with httpx.AsyncClient(timeout=60) as client_http:
            with local_path.open("rb") as f:
                img_bytes = f.read()
            files = {"media": (local_path.name, img_bytes, mime_type)}
            r = await client_http.post(url, files=files)
            r.raise_for_status()
            data = r.json()

        if "url" not in data and "media_id" not in data:
            raise ValueError(f"[{img_id}] 上传微信素材失败: {data}")

        result = {
            "wechat_url": data.get("url", ""),
            "media_id": data.get("media_id", ""),
        }
        print(f"[+] 图片 {img_id} 已上传微信: {result['wechat_url'] or result['media_id']}")
        return img_id, result


# ── 公开接口：并发生成全部图片 ───────────────────────────────────────────────

def generate_images_concurrent(
    image_prompts: list[dict],
    api_key: str,
    output_dir: Path,
    model_name: str | None = None,
    image_size: str | None = None,
    max_concurrent: int = 3,
) -> dict[str, Path]:
    """
    并发生成所有图片并下载到本地。
    返回 {img_id: local_path}
    """
    cfg = get_settings()
    if model_name is None:
        model_name = cfg.siliconflow_default_image_model
    if image_size is None:
        image_size = cfg.siliconflow_default_image_size

    async def _run():
        semaphore = asyncio.Semaphore(max_concurrent)
        tasks = [
            _async_generate_one(item, api_key, output_dir, model_name, image_size, semaphore)
            for item in image_prompts
        ]
        results = await asyncio.gather(*tasks)
        return dict(results)

    return asyncio.run(_run())


def upload_images_to_wechat_concurrent(
    local_image_map: dict[str, Path],
    access_token: str,
    max_concurrent: int = 3,
) -> dict[str, dict]:
    """
    并发将本地图片上传到微信素材库。
    返回 {img_id: {"wechat_url": "...", "media_id": "..."}}
    """
    cfg = get_settings()
    wechat_api_base = cfg.wechat_api_base

    async def _run():
        semaphore = asyncio.Semaphore(max_concurrent)
        tasks = [
            _async_upload_to_wechat(img_id, local_path, access_token, wechat_api_base, semaphore)
            for img_id, local_path in local_image_map.items()
        ]
        results = await asyncio.gather(*tasks)
        return dict(results)

    return asyncio.run(_run())


# ── 兼容旧接口（封面图单张同步生成）────────────────────────────────────────

def generate_image_from_prompt(
    image_prompt: str,
    api_key: str,
    output_dir: Path,
    model_name: str | None = None,
    image_size: str | None = None,
) -> Path:
    """
    单张图片生成（封面图，兼容旧调用）
    """
    result = generate_images_concurrent(
        image_prompts=[{"id": "cover", "prompt": image_prompt}],
        api_key=api_key,
        output_dir=output_dir,
        model_name=model_name,
        image_size=image_size,
        max_concurrent=1,
    )
    return result["cover"]
