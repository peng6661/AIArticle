"""
文章生成服务 —— 结构化 JSON 输出版
使用 Function Calling（tool_use）强制大模型返回结构化 JSON，
避免正则解析，直接得到 title / content(带占位符HTML) / image_prompts 列表。
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

from app.core.config import get_settings


# ── Function Calling 工具定义 ─────────────────────────────────────────────────
ARTICLE_TOOL = {
    "type": "function",
    "function": {
        "name": "publish_wechat_article",
        "description": "将文章结构化输出，供微信公众号直接使用",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "文章标题，吸引眼球，不超过30字",
                },
                "content": {
                    "type": "string",
                    "description": (
                        "需要插图的位置请插入占位符，格式为：【图片占位符：img_01】、【图片占位符：img_02】（序号递增）。"
                        "每篇文章建议插入 1-3 张图片。"
                        "文章正文，必须使用带有内联样式的 HTML 格式渲染"
                        "1. 小标题必须使用：<h2 style=\"font-size: 18px; font-weight: bold; color: #333333; margin-top: 20px; margin-bottom: 10px; border-left: 4px solid #007BFF; padding-left: 8px;\">标题内容</h2>\n"
                        "2. 正文段落必须使用：<p style=\"font-size: 15px; color: #555555; line-height: 1.75; letter-spacing: 1px; margin-bottom: 15px;\">段落内容</p>\n"
                        "3. 重点词汇加粗使用：<strong style=\"color: #E66A39;\">重点内容</strong>\n"
                        "4. 【强烈建议】：不要使用 <ul> 和 <li> 标签！请直接使用 <p> 标签配合序号（如 1. 2. 3.）或 Emoji（如 👉、✅、🔹）来实现列表效果。\n"
                        "5. 【严禁】：正文仅包含纯文字内容，严禁在任何位置插入图片占位符（如【图片占位符：img_xx】）。"
                    ),
                },
                "image_prompts": {
                    "type": "array",
                    "description": (
                        "正文中每个图片占位符对应的 AI 生图 prompt 列表。"
                        "若不需要文中插图，传空数组 []，同时正文中不插入任何占位符。"
                        "封面图 prompt 请放在第一个元素，id 固定为 cover。"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "占位符 ID，例如 img_01；封面图固定为 cover",
                            },
                            "prompt": {
                                "type": "string",
                                "description": "专为文章封面设计的英文 AI 生图 prompt，请根据文章主题，用一段专业的 Prompt 描述一张具有科技美感的插图，50词以内",
                            },
                        },
                        "required": ["id", "prompt"],
                    },
                },
            },
            "required": ["title", "content", "image_prompts"],
        },
    },
}

# ── System Prompt：含文中插图版（默认）───────────────────────────────────────
ARTICLE_SYSTEM_PROMPT_WITH_IMAGES = """你是一位擅长写微信公众号文章的资深自媒体作者。
请根据提供的视频文字稿，围绕指定主题创作一篇高质量的微信公众号文章。

写作要求：
1. 标题吸引眼球，引发读者好奇心，不超过 30 字
2. 排版规范：严格遵循带有内联 CSS 样式的 HTML 标签格式（使用设定好的 <h2 style="..."> 和 <p style="...">），绝对不要使用没有样式的纯标签。禁止使用 <ul> 和 <li>，用数字序号代替列表。
3. 文章主题思想和文案一样，总体内容和文案一样，核心思想和文案内容一样
4. 文章结构清晰：导语 → 主体（3-5 个小节）→ 总结/行动号召
5. 字数 800-1500 字
6. 在合适位置插入 1-3 张图片占位符：【图片占位符：img_01】、【图片占位符：img_02】……
7. image_prompts 列表第一项 id 固定为 cover（封面图），其余按正文顺序为 img_01、img_02……
8. 为每个图片（包括封面）提供对应的英文 AI 生图 prompt

你必须调用 publish_wechat_article 工具来输出结果，不要输出任何其他文字。"""

# ── System Prompt：仅封面图版（不含文中插图）────────────────────────────────
ARTICLE_SYSTEM_PROMPT_COVER_ONLY = """你是一位擅长写微信公众号文章的资深自媒体作者。
请根据提供的视频文字稿，围绕指定主题创作一篇高质量的微信公众号文章。

写作要求：
1. 标题吸引眼球，引发读者好奇心，不超过 30 字
2. 排版规范：严格遵循带有内联 CSS 样式的 HTML 标签格式（使用设定好的 <h2 style="..."> 和 <p style="...">），绝对不要使用没有样式的纯标签。禁止使用 <ul> 和 <li>，用数字序号代替列表。
3. 语言生动活泼，符合微信公众号阅读习惯，贴近读者
4. 文章主题思想和文案一样，总体内容和文案一样，核心思想和文案内容一样
5. 字数 800-1500 字
6. 正文中【不要】插入任何图片占位符，保持纯文字 HTML
7. image_prompts 列表只需一项，id 固定为 cover，prompt 描述整篇文章的封面配图风格

你必须调用 publish_wechat_article 工具来输出结果，不要输出任何其他文字。"""


def _ensure_openai():
    try:
        return importlib.import_module("openai")
    except ImportError:
        print("未检测到依赖 openai，正在自动安装...")
        subprocess.run([sys.executable, "-m", "pip", "install", "openai"], check=True)
        return importlib.import_module("openai")


def _read_material(material_path: Path) -> str:
    """读取文案素材，支持单文件或目录"""
    if material_path.is_dir():
        texts = []
        for txt_file in sorted(material_path.glob("*.txt")):
            texts.append(txt_file.read_text(encoding="utf-8"))
        if not texts:
            raise FileNotFoundError(f"目录中没有找到 .txt 文件: {material_path}")
        return "\n\n---\n\n".join(texts)
    if not material_path.exists():
        raise FileNotFoundError(f"素材文件不存在: {material_path}")
    return material_path.read_text(encoding="utf-8")


def _parse_tool_call_result(response) -> dict:
    """
    从 Function Calling 响应中解析出工具参数 JSON。
    兼容两种情况：
      1. 模型正确调用了工具（tool_calls）
      2. 模型不支持 Function Calling，回退到正文中提取 JSON
    """
    # ── 优先从 tool_calls 中提取 ─────────────────────────────────────────────
    msg = response.choices[0].message
    if msg.tool_calls:
        for tc in msg.tool_calls:
            if tc.function.name == "publish_wechat_article":
                return json.loads(tc.function.arguments)

    # ── 回退：从文本内容中提取 JSON ──────────────────────────────────────────
    content = (msg.content or "").strip()
    # 去掉 markdown 代码块
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(
            line for line in lines
            if not line.startswith("```")
        ).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # 最后兜底：尝试找第一个 { ... } 块
        start = content.find("{")
        end = content.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(content[start:end])
        raise ValueError(
            "模型未调用工具且响应不含合法 JSON，请检查模型是否支持 Function Calling。\n"
            f"原始响应：{content[:300]}"
        )


def generate_article(
    material_path: Path,
    topic: str | None = None,
    extra_requirements: str = "",
    api_key: str = "",
    model_name: str | None = None,
    temperature: float | None = None,
    generate_inline_images: bool = True,
) -> dict:
    """
    根据素材和主题生成文章，通过 Function Calling 返回结构化 JSON。

    generate_inline_images=True（默认）：
        正文含图片占位符，image_prompts 包含封面(id=cover)和文中插图(id=img_01...)
    generate_inline_images=False：
        正文无占位符，image_prompts 只有封面一项(id=cover)

    返回格式：
    {
        "title": "文章标题",
        "content": "<p>正文 HTML</p>...",
        "image_prompts": [
            {"id": "cover",  "prompt": "封面图描述..."},
            {"id": "img_01", "prompt": "文中图1描述..."},   # 仅 generate_inline_images=True 时有
        ]
    }
    """
    cfg = get_settings()
    openai_mod = _ensure_openai()
    OpenAI = openai_mod.OpenAI

    if topic is None:
        topic = cfg.article_default_topic
    if model_name is None:
        model_name = cfg.siliconflow_default_text_model
    if temperature is None:
        temperature = cfg.siliconflow_default_temperature

    # 根据开关选择 System Prompt
    system_prompt = (
        ARTICLE_SYSTEM_PROMPT_WITH_IMAGES
        if generate_inline_images
        else ARTICLE_SYSTEM_PROMPT_COVER_ONLY
    )

    material_text = _read_material(material_path)
    user_message = f"主题：{topic}\n\n视频文字稿素材：\n{material_text}"
    if extra_requirements:
        user_message += f"\n\n额外写作要求：{extra_requirements}"

    client = OpenAI(api_key=api_key, base_url=cfg.siliconflow_base_url)

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        tools=[ARTICLE_TOOL],
        tool_choice={"type": "function", "function": {"name": "publish_wechat_article"}},
        temperature=temperature,
        max_tokens=cfg.siliconflow_max_tokens,
    )

    article_data = _parse_tool_call_result(response)

    # 保证字段完整
    article_data.setdefault("title", "未命名文章")
    article_data.setdefault("content", "")
    article_data.setdefault("image_prompts", [])

    # ── 若关闭了文中插图，确保正文里没有残留占位符 ───────────────────────────
    if not generate_inline_images:
        import re
        article_data["content"] = re.sub(
            r'【图片占位符[：:]\s*[A-Za-z0-9_]+\s*】', "", article_data["content"]
        )
        # image_prompts 只保留 cover，其余丢弃
        article_data["image_prompts"] = [
            p for p in article_data["image_prompts"] if p.get("id") == "cover"
        ]
        # 若模型忘记生成 cover，兜底补一个
        if not article_data["image_prompts"]:
            article_data["image_prompts"] = [{
                "id": "cover",
                "prompt": (
                    "A vibrant, modern illustration for a Chinese social media article "
                    "about AI and technology, clean professional colorful style"
                ),
            }]

    return article_data
