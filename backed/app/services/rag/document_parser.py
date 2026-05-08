"""
多格式文档解析器
支持纯文本、Markdown、PDF、SRT 字幕、历史文章等格式的解析和清洗。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import select

from app.db.database import get_db_ctx
from app.db.models import PipelineJobModel


def parse_text(content: str) -> str:
    """解析纯文本，去除多余空白。"""
    text = content.strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def parse_markdown(content: str) -> str:
    """
    解析 Markdown，去除格式标记保留纯文本。
    保留段落结构，去除代码块、链接、图片等标记。
    """
    text = content
    # 去除代码块
    text = re.sub(r"```[\s\S]*?```", " ", text)
    # 去除行内代码
    text = re.sub(r"`[^`]*`", " ", text)
    # 去除图片
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    # 去除链接，保留文字
    text = re.sub(r"\[([^\]]*)\]\([^)]+\)", r"\1", text)
    # 去除标题标记但保留文字
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    # 去除加粗/斜体标记
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
    # 去除删除线
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    # 去除引用标记
    text = re.sub(r"^>\s*", "", text, flags=re.M)
    # 去除列表标记
    text = re.sub(r"^[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.M)
    # 去除水平线
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.M)
    # 去除 HTML 标签
    text = re.sub(r"<[^>]+>", " ", text)
    # 清理多余空白
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return text


def parse_pdf(file_path: Path) -> str:
    """
    解析 PDF 文件，提取文本内容。
    需要 pypdf 库。
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ImportError("需要安装 pypdf：pip install pypdf")

    if not file_path.exists():
        raise FileNotFoundError(f"PDF 文件不存在: {file_path}")

    reader = PdfReader(str(file_path))
    pages_text = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages_text.append(text.strip())

    full_text = "\n\n".join(pages_text)
    full_text = re.sub(r"\n{3,}", "\n\n", full_text)
    return full_text.strip()


def parse_srt(content: str) -> str:
    """
    解析 SRT 字幕格式，提取纯文本。
    格式示例：
        1
        00:00:01,000 --> 00:00:04,000
        这是第一句字幕

        2
        00:00:05,000 --> 00:00:08,000
        这是第二句字幕
    """
    lines = []
    for line in content.split("\n"):
        line = line.strip()
        # 跳过序号行（纯数字）
        if re.match(r"^\d+$", line):
            continue
        # 跳过时间码行
        if re.match(r"\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}", line):
            continue
        # 跳过空行
        if not line:
            continue
        # 去除 HTML 标签（有些字幕带有 <b> 等）
        line = re.sub(r"<[^>]+>", "", line)
        lines.append(line)

    text = "\n".join(lines)
    # 合并重复的连续行（SRT 常见问题）
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def parse_history_article(job_id: str) -> str:
    """
    从已完成的 pipeline 任务中提取知识内容。
    合并转写文本和生成的文章 Markdown。
    """
    with get_db_ctx() as db:
        model = db.scalar(
            select(PipelineJobModel).where(PipelineJobModel.job_id == job_id)
        )
        if not model:
            raise ValueError(f"任务不存在: {job_id}")

        parts = []
        if model.video_title:
            parts.append(f"标题：{model.video_title}")
        if model.transcript_text:
            parts.append(f"原始转写：\n{model.transcript_text}")
        if model.article_body_markdown:
            parts.append(f"生成文章：\n{model.article_body_markdown}")

        if not parts:
            raise ValueError(f"任务 {job_id} 没有可提取的内容")

        return "\n\n---\n\n".join(parts)


def clean_text(text: str) -> str:
    """
    通用文本清洗：去除语气词、乱码、多余空白。
    """
    # 去除常见语气词（中文）
    filler_words = ["嗯", "啊", "呃", "额", "那个", "就是说", "然后呢", "对吧", "你知道吗"]
    for word in filler_words:
        text = text.replace(word, "")
    # 去除多余空白行
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 去除行首行尾空白
    text = "\n".join(line.strip() for line in text.split("\n"))
    return text.strip()
