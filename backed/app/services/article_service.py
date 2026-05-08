"""
文章生成服务 —— 结构化 JSON 输出版（Markdown格式）
使用 Function Calling（tool_use）强制大模型返回结构化 JSON，
避免正则解析，直接得到 title / content(带占位符Markdown) / image_prompts 列表。
"""
from __future__ import annotations

import importlib
import json
import re
import subprocess
import sys
from pathlib import Path

from app.core.config import get_settings


TARGET_MIN_CHARS = 1000
TARGET_MAX_CHARS = 1500
REQUIRED_MAJOR_SECTIONS = 3
MIN_EXAMPLE_MARKERS = 2

AI_CLICHE_PHRASES = [
    "总的来说",
    "综上所述",
    "值得注意的是",
    "值得一提的是",
    "不难发现",
    "可以说",
    "毋庸置疑",
    "不可否认",
    "在当今这个",
    "在这个快节奏的时代",
    "随着技术的不断发展",
    "赋能",
    "闭环",
    "底层逻辑",
    "颗粒度",
]

AI_CONNECTOR_PHRASES = [
    "此外",
    "另外",
    "与此同时",
    "同时",
    "首先",
    "其次",
    "最后",
]


# ── Function Calling 工具定义 ─────────────────────────────────────────────────
ARTICLE_TOOL = {
    "type": "function",
    "function": {
        "name": "publish_markdown_article",
        "description": "将文章结构化输出，使用 Markdown 格式，供微信公众号最终转换使用",
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
                        "文章正文，必须使用 Markdown 格式渲染。"
                        "需要插图的位置请插入占位符，格式为：【图片占位符：img_01】、【图片占位符：img_02】（序号递增），占位符必须单独成行。"
                        "每篇文章建议插入 1-3 张图片。"
                        "结构要求："
                        "1. 正文必须包含 3-5 个一级小节，一级小节必须使用 ## 标题内容"
                        "2. 每个一级小节下至少包含 1 个二级小节，二级小节必须使用 ### 标题内容"
                        "3. 导语和结尾必须独立成段，段落之间空一行"
                        "4. 重点词汇使用 **加粗** 或 *斜体*"
                        "5. 列表使用数字序号（1. 2. 3.）或项目符号（- * +）"
                        "6. 引用使用 > 引用内容"
                        "7. 代码块使用 ```语言名\n代码内容```"
                        "8. 正文字数必须稳定在 1000-1500 字之间，理想范围 1100-1300 字"
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
                                "description": "英文 AI 生图 prompt，请根据图片在文章中的位置和内容，生成专业的描述（50词以内），封面图需要突出主题和科技感",
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
2. 排版规范：必须使用 Markdown 格式，不要使用任何 HTML 标签
3. 文章主题思想和文案一致，但不能只是转写稿改写，必须补足背景、分析、观点和总结
4. 文章结构必须清晰：导语 → 主体（3-5 个一级小节）→ 总结/行动号召
5. 正文字数必须稳定在 1000-1500 字之间，优先控制在 1100-1300 字
6. 在合适位置插入 1-3 张图片占位符：【图片占位符：img_01】、【图片占位符：img_02】……占位符单独成行
7. image_prompts 列表第一项 id 固定为 cover（封面图），其余按正文顺序为 img_01、img_02……
8. 为每个图片（包括封面）提供对应的英文 AI 生图 prompt
9. Markdown 格式规范：
   - 正文不要再写 # 主标题，标题单独放在 title 字段
   - 一级小节必须使用 ##
   - 二级小节必须使用 ###
   - 段落之间空一行
   - 强调使用 **加粗** 或 *斜体*
   - 列表使用 1. 2. 3. 或 - * +
   - 引用使用 >
   - 代码块使用 ```语言名\n代码```
10. 每个 ## 小节下必须至少包含一个 ### 小标题，不能只有纯段落堆叠
11. 当原始转写内容较短时，要主动补充场景解释、原因分析、方法拆解和落地建议，保证成文长度和可读性
12. 去除明显 AI 味：不要堆砌“总的来说、综上所述、值得注意的是、可以说、赋能、底层逻辑”这类高频套话
13. 句子节奏要有人写作的起伏：短句、长句穿插，不要整篇都用差不多长度的句子
14. 每个一级小节至少加入一个具体场景、例子、细节或代价判断，少讲空泛正确话
15. 少用机械连接词串联段落，不要反复使用“首先/其次/最后/此外/与此同时/另外”
16. 允许有明确态度和判断，像经验丰富的作者在解释问题，而不是像说明书在复述结论

你必须调用 publish_markdown_article 工具来输出结果，不要输出任何其他文字。"""

# ── System Prompt：仅封面图版（不含文中插图）────────────────────────────────
ARTICLE_SYSTEM_PROMPT_COVER_ONLY = """你是一位擅长写微信公众号文章的资深自媒体作者。
请根据提供的视频文字稿，围绕指定主题创作一篇高质量的微信公众号文章。

写作要求：
1. 标题吸引眼球，引发读者好奇心，不超过 30 字
2. 排版规范：必须使用 Markdown 格式，不要使用任何 HTML 标签
3. 语言生动活泼，符合微信公众号阅读习惯，贴近读者
4. 文章主题思想和文案一致，但不能只是转写稿改写，必须补足背景、分析、观点和总结
5. 正文字数必须稳定在 1000-1500 字之间，优先控制在 1100-1300 字
6. 正文中【不要】插入任何图片占位符，保持纯文字 Markdown
7. image_prompts 列表只需一项，id 固定为 cover，prompt 描述整篇文章的封面配图风格
8. Markdown 格式规范：
   - 正文不要再写 # 主标题，标题单独放在 title 字段
   - 一级小节必须使用 ##
   - 二级小节必须使用 ###
   - 段落之间空一行
   - 强调使用 **加粗** 或 *斜体*
   - 列表使用 1. 2. 3. 或 - * +
   - 引用使用 >
9. 正文必须包含 3-5 个 ## 一级小节，并且每个一级小节下至少包含一个 ### 二级小节
10. 当原始转写内容较短时，要主动补充场景解释、原因分析、方法拆解和落地建议，保证成文长度和可读性
11. 去除明显 AI 味：不要堆砌“总的来说、综上所述、值得注意的是、可以说、赋能、底层逻辑”这类高频套话
12. 句子节奏要有人写作的起伏：短句、长句穿插，不要整篇都用差不多长度的句子
13. 每个一级小节至少加入一个具体场景、例子、细节或代价判断，少讲空泛正确话
14. 少用机械连接词串联段落，不要反复使用“首先/其次/最后/此外/与此同时/另外”
15. 允许有明确态度和判断，像经验丰富的作者在解释问题，而不是像说明书在复述结论

你必须调用 publish_markdown_article 工具来输出结果，不要输出任何其他文字。"""


def _plain_text_length(markdown_text: str) -> int:
    text = re.sub(r"```[\s\S]*?```", " ", markdown_text)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^>\s*", "", text, flags=re.M)
    text = re.sub(r"^[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.M)
    text = re.sub(r"【图片占位符[：:]\s*[A-Za-z0-9_]+\s*】", " ", text)
    text = re.sub(r"[*_~#>\-\[\]()!`]", " ", text)
    text = re.sub(r"\s+", "", text)
    return len(text)


def _count_heading(markdown_text: str, prefix: str) -> int:
    return len(re.findall(rf"^{re.escape(prefix)}\s+\S+", markdown_text, flags=re.M))


def _count_occurrences(text: str, phrases: list[str]) -> int:
    return sum(text.count(phrase) for phrase in phrases)


def _count_example_markers(text: str) -> int:
    markers = ["比如", "例如", "举个例子", "拿", "你会发现", "如果你", "说白了", "就像"]
    return _count_occurrences(text, markers)


def _sentence_length_variance(text: str) -> float:
    plain_text = re.sub(r"【图片占位符[：:]\s*[A-Za-z0-9_]+\s*】", "", text)
    sentences = [
        s.strip() for s in re.split(r"[。！？；\n]+", plain_text)
        if s and s.strip()
    ]
    if len(sentences) < 4:
        return 0.0
    lengths = [len(s) for s in sentences]
    return (max(lengths) - min(lengths)) / max(sum(lengths) / len(lengths), 1)


def _has_repeated_sentence_openers(text: str) -> bool:
    plain_text = re.sub(r"【图片占位符[：:]\s*[A-Za-z0-9_]+\s*】", "", text)
    sentences = [
        s.strip() for s in re.split(r"[。！？；\n]+", plain_text)
        if s and s.strip()
    ]
    openers: dict[str, int] = {}
    for sentence in sentences:
        opener = sentence[:4]
        if len(opener) < 2:
            continue
        openers[opener] = openers.get(opener, 0) + 1
    return any(count >= 3 for count in openers.values())


def _needs_article_retry(article_data: dict, generate_inline_images: bool) -> str | None:
    content = (article_data.get("content") or "").strip()
    if not content:
        return "正文为空"

    text_length = _plain_text_length(content)
    major_sections = _count_heading(content, "##")
    minor_sections = _count_heading(content, "###")
    cliche_count = _count_occurrences(content, AI_CLICHE_PHRASES)
    connector_count = _count_occurrences(content, AI_CONNECTOR_PHRASES)
    example_count = _count_example_markers(content)
    sentence_variance = _sentence_length_variance(content)

    if text_length < TARGET_MIN_CHARS:
        return f"正文字数不足，当前约 {text_length} 字，需要扩写到 {TARGET_MIN_CHARS}-{TARGET_MAX_CHARS} 字"
    if text_length > TARGET_MAX_CHARS:
        return f"正文字数过长，当前约 {text_length} 字，需要压缩到 {TARGET_MIN_CHARS}-{TARGET_MAX_CHARS} 字"
    if major_sections < REQUIRED_MAJOR_SECTIONS:
        return f"一级小节不足，当前只有 {major_sections} 个 ## 标题，需要至少 {REQUIRED_MAJOR_SECTIONS} 个"
    if minor_sections < major_sections:
        return "二级小节不足，每个一级小节下至少需要一个 ### 标题"
    if generate_inline_images and "【图片占位符" not in content:
        return "正文缺少图片占位符"
    if cliche_count >= 2:
        return "正文套话偏多，AI 味较重，需要减少模板化表达和空泛总结"
    if connector_count >= 6:
        return "机械连接词过多，段落推进像提纲展开，不像自然写作"
    if example_count < MIN_EXAMPLE_MARKERS:
        return "具体例子或场景太少，正文偏空，需要补充真实场景和细节"
    if sentence_variance < 1.2:
        return "句长变化太小，整体节奏过于平均，容易显得像 AI 生成"
    if _has_repeated_sentence_openers(content):
        return "多句开头过于重复，语言节奏太整齐，需要改写得更自然"
    return None


def _build_retry_messages(system_prompt: str, user_message: str, article_data: dict, reason: str) -> list[dict[str, str]]:
    previous_json = json.dumps(article_data, ensure_ascii=False)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
        {
            "role": "assistant",
            "content": previous_json,
        },
        {
            "role": "user",
            "content": (
                "上一版结果不符合要求，请整体重写，不要只做局部修补。\n"
                f"不符合原因：{reason}\n"
                f"请严格满足：正文字数 {TARGET_MIN_CHARS}-{TARGET_MAX_CHARS} 字、"
                "3-5 个 ## 一级小节、每个一级小节至少一个 ### 二级小节、"
                "导语和结尾独立成段、保持微信公众号文章风格，"
                "少用空泛总结句，多用具体场景、鲜明判断和自然句式。"
            ),
        },
    ]


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
            if tc.function.name == "publish_markdown_article":
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
    base_url: str | None = None,
    max_tokens: int | None = None,
    rag_collection: str | None = None,
    rag_top_k: int = 5,
    rag_embedding_model: str | None = None,
    rag_embedding_provider: str | None = None,
) -> dict:
    """
    根据素材和主题生成文章，通过 Function Calling 返回结构化 JSON。

    generate_inline_images=True（默认）：
        正文含图片占位符，image_prompts 包含封面(id=cover)和文中插图(id=img_01...)
    generate_inline_images=False：
        正文无占位符，image_prompts 只有封面一项(id=cover)

    base_url：AI 服务端点，留空默认使用 SiliconFlow。
               传入智谱端点 https://open.bigmodel.cn/api/paas/v4 即可切换到智谱。

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
    if base_url is None:
        base_url = cfg.siliconflow_base_url
    if max_tokens is None:
        max_tokens = cfg.siliconflow_max_tokens

    # 根据开关选择 System Prompt
    system_prompt = (
        ARTICLE_SYSTEM_PROMPT_WITH_IMAGES
        if generate_inline_images
        else ARTICLE_SYSTEM_PROMPT_COVER_ONLY
    )

    material_text = _read_material(material_path)

    # RAG 检索增强：从知识库获取相关上下文
    rag_context = ""
    if rag_collection:
        try:
            from app.services.rag.rag_service import rag_service
            rag_context = rag_service.retrieve_context(
                collection_name=rag_collection,
                query_text=material_text,
                api_key=api_key,
                top_k=rag_top_k,
                embedding_model=rag_embedding_model,
                embedding_provider=rag_embedding_provider,
            )
        except Exception as e:
            print(f"[RAG] 检索失败（将忽略 RAG 继续生成）: {e}")

    # 构建 prompt
    if rag_context:
        user_message = f"主题：{topic}\n\n参考知识：\n{rag_context}\n\n视频文字稿素材：\n{material_text}"
    else:
        user_message = f"主题：{topic}\n\n视频文字稿素材：\n{material_text}"
    if extra_requirements:
        user_message += f"\n\n额外写作要求：{extra_requirements}"

    client = OpenAI(api_key=api_key, base_url=base_url)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        tools=[ARTICLE_TOOL],
        tool_choice={"type": "function", "function": {"name": "publish_markdown_article"}},
        temperature=temperature,
        max_tokens=max_tokens,
    )

    article_data = _parse_tool_call_result(response)

    retry_reason = _needs_article_retry(article_data, generate_inline_images)
    if retry_reason:
        retry_response = client.chat.completions.create(
            model=model_name,
            messages=_build_retry_messages(system_prompt, user_message, article_data, retry_reason),
            tools=[ARTICLE_TOOL],
            tool_choice={"type": "function", "function": {"name": "publish_markdown_article"}},
            temperature=temperature,
            max_tokens=max_tokens,
        )
        article_data = _parse_tool_call_result(retry_response)

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
