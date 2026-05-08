"""
微信公众号草稿发布服务
核心新增：
  - upload_cover_image()     上传封面图，返回 media_id
  - replace_image_placeholders() 将正文 HTML 中的占位符替换为微信图片标签
  - publish_draft()          组装发布，成功后自动开浏览器
业务逻辑来自 wechat_draft_from_html.py，在其基础上扩展
"""
from __future__ import annotations

import json
import mimetypes
import re
import webbrowser
from pathlib import Path

import requests

from app.core.config import get_settings


# ── Access Token ──────────────────────────────────────────────────────────────

def get_access_token(appid: str, appsecret: str) -> str:
    cfg = get_settings()
    url = f"{cfg.wechat_api_base}/cgi-bin/token"
    params = {"grant_type": "client_credential", "appid": appid, "secret": appsecret}
    resp = requests.get(url, params=params, timeout=30)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        raise ValueError(f"获取 access_token 失败: {json.dumps(data, ensure_ascii=False)}")
    return data["access_token"]


# ── 封面图上传（永久素材 thumb）────────────────────────────────────────────────

def upload_cover_image(access_token: str, image_path: Path) -> str:
    """
    上传封面缩略图（thumb 类型），返回 media_id。
    用于草稿 thumb_media_id 字段。
    """
    cfg = get_settings()
    if not image_path.exists():
        raise FileNotFoundError(f"封面图不存在: {image_path}")

    mime_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    url = (
        f"{cfg.wechat_api_base}/cgi-bin/material/add_material"
        f"?access_token={access_token}&type=thumb"
    )
    with image_path.open("rb") as f:
        resp = requests.post(url, files={"media": (image_path.name, f, mime_type)}, timeout=60)

    resp.encoding = "utf-8"
    resp.raise_for_status()
    data = resp.json()
    media_id = data.get("media_id")
    if not media_id:
        raise ValueError(f"上传封面图失败: {json.dumps(data, ensure_ascii=False)}")
    return media_id


# ── 正文图片替换占位符 ─────────────────────────────────────────────────────────

def replace_image_placeholders(
    content_html: str,
    wechat_image_map: dict[str, dict],
) -> str:
    """
    将正文 HTML 中的图片占位符替换为微信域内图片标签。

    占位符格式（支持全角/半角冒号、前后有无空格）：
        【图片占位符：img_01】
        【图片占位符:img_01】

    替换为：
        <img src="微信返回的wechat_url" style="max-width:100%;display:block;margin:12px auto;" />
    如果某个 id 没有对应 URL，保留原占位符不替换（避免静默丢失）。
    """
    def _replacer(match: re.Match) -> str:
        img_id = match.group(1).strip()
        info = wechat_image_map.get(img_id)
        if not info or not info.get("wechat_url"):
            # 没有对应图片，保留占位符原文
            return match.group(0)
        url = info["wechat_url"]
        return (
            f'<img src="{url}" '
            f'style="max-width:100%;height:auto;display:block;margin:12px auto;" />'
        )

    # 匹配 【图片占位符：img_xx】 或 【图片占位符:img_xx】
    pattern = r'【图片占位符[：:]\s*([A-Za-z0-9_]+)\s*】'
    return re.sub(pattern, _replacer, content_html)


# ── 原创声明注入 ──────────────────────────────────────────────────────────────
def inject_original_notice(
    content_html: str, notice_text: str, put_at_top: bool = True
) -> str:
    # 逻辑判断：如果 notice_text 为空字符串或仅包含空格
    # 则使用你指定的 HTML 格式作为默认值
    if not notice_text or not notice_text.strip():
        notice_content = (
            '关注公众号<span style="color: #ff0000;"><strong>「阿鹏随笔录」</strong></span>'
            '回复<span style="color: #ff0000;"><strong>「资料」</strong></span>'
            '获得更多学习干货！！！'
        )
    else:
        # 如果传入了 notice_text，则使用传入的内容
        notice_content = notice_text.strip()

    # 构建符合要求的 HTML 块
    # text-align: center -> 居中
    # font-size: 12px -> 字体大小
    # font-weight: bold -> 全文加粗
    notice_block = (
        '<section style="margin: 16px 0; text-align: center; font-size: 12px; font-weight: bold;">'
        f'<p style="line-height: 1.8; color: #333; margin: 0;">'
        f"{notice_content}"
        "</p>"
        "</section>"
    )

    # 根据位置参数返回拼接后的内容
    if put_at_top:
        return f"{notice_block}\n{content_html}"
    else:
        return f"{content_html}\n{notice_block}"

# ── 从 HTML 中提取标题（兜底）────────────────────────────────────────────────

def extract_title_from_html(html_text: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_text, "html.parser")
    if soup.title and soup.title.get_text(strip=True):
        return soup.title.get_text(strip=True)
    for h in soup.find_all(["h1", "h2"]):
        text = h.get_text(strip=True)
        if text:
            return text
    lines = [l.strip() for l in soup.get_text("\n").splitlines() if l.strip()]
    if lines:
        return lines[0]
    raise ValueError("无法从 HTML 中提取标题")


# ── 新增草稿 ──────────────────────────────────────────────────────────────────

def add_draft(
    access_token: str,
    title: str,
    content_html: str,
    thumb_media_id: str,
    author: str | None = None,
    digest: str | None = None,
    content_source_url: str | None = None,
    need_open_comment: int | None = None,
    only_fans_can_comment: int | None = None,
) -> dict:
    cfg = get_settings()
    url = f"{cfg.wechat_api_base}/cgi-bin/draft/add?access_token={access_token}"
    payload = {
        "articles": [{
            "title": title,
            "author": author or cfg.wechat_default_author,
            "digest": digest or cfg.wechat_default_digest,
            "content": content_html,
            "content_source_url": content_source_url or cfg.wechat_default_content_source_url,
            "thumb_media_id": thumb_media_id,
            "need_open_comment": need_open_comment if need_open_comment is not None else cfg.wechat_need_open_comment,
            "only_fans_can_comment": only_fans_can_comment if only_fans_can_comment is not None else cfg.wechat_only_fans_can_comment,
        }]
    }
    headers = {"Content-Type": "application/json; charset=utf-8"}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp = requests.post(url, data=body, headers=headers, timeout=60)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    data = resp.json()
    if data.get("errcode", 0) != 0:
        raise ValueError(f"新建草稿失败: {json.dumps(data, ensure_ascii=False)}")
    return data


def get_draft(access_token: str, media_id: str) -> dict:
    cfg = get_settings()
    url = f"{cfg.wechat_api_base}/cgi-bin/draft/get?access_token={access_token}"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    body = json.dumps({"media_id": media_id}, ensure_ascii=False).encode("utf-8")
    resp = requests.post(url, data=body, headers=headers, timeout=60)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    data = resp.json()
    if data.get("errcode", 0) != 0 and "news_item" not in data:
        raise ValueError(f"获取草稿详情失败: {json.dumps(data, ensure_ascii=False)}")
    return data


# ── 主流程：发布草稿 ──────────────────────────────────────────────────────────

def publish_draft(
    appid: str,
    appsecret: str,
    content_html: str,          # 已替换图片占位符的最终正文 HTML
    cover_image_path: Path,     # 封面图本地路径（上传为 thumb 素材）
    title: str | None = None,
    author: str | None = None,
    digest: str | None = None,
    content_source_url: str | None = None,
    original_notice: str | None = None,
) -> dict:
    """
    完整发布流程：
    1. 获取 access_token
    2. 上传封面图（thumb 类型），获取 thumb_media_id
    3. 注入原创声明
    4. 调用新增草稿接口
    5. 获取草稿预览 URL
    6. 自动在浏览器打开草稿页供用户继续编辑
    返回 {"media_id": "...", "preview_url": "..."}
    """
    cfg = get_settings()
    if original_notice is None:
        original_notice = cfg.wechat_default_original_notice

    # ── 注入原创声明 ──────────────────────────────────────────────────────────
    final_html = inject_original_notice(content_html, original_notice, put_at_top=False)

    # ── 标题兜底 ──────────────────────────────────────────────────────────────
    if not title:
        try:
            title = extract_title_from_html(content_html)
        except ValueError:
            title = "未命名文章"

    # ── 微信接口调用 ──────────────────────────────────────────────────────────
    access_token = get_access_token(appid, appsecret)
    thumb_media_id = upload_cover_image(access_token, cover_image_path)

    result = add_draft(
        access_token=access_token,
        title=title,
        content_html=final_html,
        thumb_media_id=thumb_media_id,
        author=author,
        digest=digest,
        content_source_url=content_source_url,
    )

    media_id = result.get("media_id")
    preview_url = None
    if media_id:
        try:
            draft_detail = get_draft(access_token, media_id)
            news_items = draft_detail.get("news_item", [])
            if news_items:
                preview_url = news_items[0].get("url")
        except Exception:
            pass

    # ── 草稿创建成功后自动打开浏览器 ─────────────────────────────────────────
    draft_list_url = cfg.get("wechat", "mp_draft_list_url", default="https://mp.weixin.qq.com/")
    open_url = preview_url or draft_list_url
    try:
        webbrowser.open(open_url)
        print(f"[+] 已在浏览器打开草稿页: {open_url}")
    except Exception as e:
        print(f"[!] 打开浏览器失败: {e}")

    return {"media_id": media_id, "preview_url": preview_url, "raw_result": result}
