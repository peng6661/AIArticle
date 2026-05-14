"""
Step 4：基于 RAG + 大模型直调的文章生成系统（结构化 JSON 输出版）。

使用 Function Calling（tool_use）强制大模型返回结构化 JSON，
避免正则解析，直接得到 title / content(带占位符Markdown) / image_prompts 列表。

流程：
  1. 从 ChromaDB 检索相关知识（如有配置 RAG 集合）
  2. 如果文案过长（>5k 字符），先用 LLM 压缩为摘要
  3. 构造带有写作风格约束的 prompt，通过 Function Calling 调用大模型
  4. 质量检查 + 自动重写（如果不符合要求）
  5. 解析标题、回写 MySQL
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.db.database import get_db_ctx
from app.db.models import ContentTaskModel

logger = logging.getLogger(__name__)

# =============================================================================
# 工具函数
# =============================================================================


def _update_task(task_id: str, **kwargs: Any) -> None:
    """更新 content_tasks 表中的字段（状态 + 中间产物）。"""
    with get_db_ctx() as db:
        task = db.scalar(
            select(ContentTaskModel).where(ContentTaskModel.task_id == task_id)
        )
        if not task:
            logger.warning(f"[Step4] task_id={task_id} 不存在，跳过回写")
            return
        for k, v in kwargs.items():
            setattr(task, k, v)
        task.updated_at = datetime.utcnow()
        db.flush()


def _ensure_openai() -> Any:
    """加载 openai 模块（pip 安装）。"""
    try:
        import openai as openai_mod

        logger.debug("使用 pip 安装的 openai 库")
        return openai_mod
    except ImportError:
        raise ImportError("请安装 openai 库：pip install openai")


def _call_model_text(
    client: Any,
    system_prompt: str,
    user_message: str,
    model: str = "Qwen/Qwen2.5-7B-Instruct",
    max_tokens: int = 2048,
    temperature: float = 0.7,
) -> str | None:
    """通用文本生成调用（兼容 OpenAI SDK 和 API 直调）。"""
    config = get_settings()

    try:
        # 优先使用 ChatCompletion（OpenAI SDK）
        if hasattr(client.chat, "completions") and hasattr(
            client.chat.completions, "create"
        ):
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                stream=False,
            )
            return resp.choices[0].message.content

        # 回退：API 直调
        resp = client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    except Exception as e:
        logger.error(f"[Step4/LLM] 调用失败: {e}")
        return None


def _get_llm_client(api_key: str, ai_provider: str = "siliconflow"):
    """
    创建并返回 OpenAI SDK Client 对象。

    Args:
        api_key: API Key
        ai_provider: "siliconflow" | "zhipu"

    Returns:
        openai.OpenAI 实例
    """
    openai = _ensure_openai()
    config = get_settings()
    ai_cfg = config.get_ai_provider_config(ai_provider)

    base_url = ai_cfg.get("base_url", "")

    logger.debug(f"[Step4] 创建 LLM Client | provider={ai_provider} | base_url={base_url}")
    return openai.OpenAI(api_key=api_key, base_url=base_url)


def _call_llm(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 2048,
    temperature: float = 0.7,
    api_key: str = "",
    ai_provider: str = "siliconflow",
    text_model: str = "",
) -> str:
    """
    统一的 LLM 调用封装。

    Args:
        system_prompt: 系统提示词
        user_message: 用户输入
        max_tokens: 最大输出 token 数
        temperature: 温度
        api_key: API Key
        ai_provider: 服务商
        text_model: 前端选择的模型名称（优先），为空则从配置读取

    Returns:
        模型输出文本
    """
    client = _get_llm_client(api_key, ai_provider)
    config = get_settings()
    ai_cfg = config.get_ai_provider_config(ai_provider)

    # 优先级：传参 > 配置 > 社区默认模型
    model = text_model or ai_cfg.get("default_text_model", "Qwen/Qwen3-14B")

    result = _call_model_text(
        client=client,
        system_prompt=system_prompt,
        user_message=user_message,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return result or ""


# =============================================================================
# ChromaDB 检索
# =============================================================================


def _retrieve_knowledge(transcript: str, task_id: str, api_key: str) -> str:
    """
    从 ChromaDB 检索相关知识上下文。

    Args:
        transcript: 原始转写文本
        task_id: 任务 ID，用于从 DB 获取 rag_collection
        api_key: SiliconFlow API Key，用于向量检索认证

    Returns:
        检索到的知识上下文，失败或未配置时返回空字符串。
    """
    cfg = get_settings()

    # 从 DB 读取 task 记录的 rag_collection
    task = get_content_task(task_id)
    if not task:
        logger.info(f"[Step4/RAG] task_id={task_id} 不存在，跳过知识检索")
        return ""
    rag_collection = task.get("rag_collection", "")
    if not rag_collection:
        logger.info(f"[Step4/RAG] 任务未配置 RAG 集合，跳过知识检索 | task_id={task_id}")
        return ""

    try:
        from app.services.rag.rag_service import RagService

        # 使用任务中存储的 embedding 配置（前端选择的），留空则使用 config 默认值
        emb_model = task.get("rag_embedding_model") or None
        emb_provider = task.get("rag_embedding_provider") or None
        emb_api_key = task.get("rag_embedding_api_key") or cfg.rag_embedding_api_key or None
        top_k = int(task.get("rag_top_k") or cfg.rag_top_k)

        rag = RagService()
        context = rag.retrieve_context(
            collection_name=rag_collection,
            query_text=transcript[:2000],
            api_key=api_key,
            top_k=top_k,
            embedding_model=emb_model,
            embedding_provider=emb_provider,
            embedding_api_key=emb_api_key,
        )
        logger.info(f"[Step4/RAG] 检索到 {len(context)} 字符上下文 | collection={rag_collection}")
        return context
    except Exception as e:
        logger.warning(f"[Step4/RAG] 检索失败: {e}")
        return ""


def _compress_transcript(
    transcript: str,
    api_key: str,
    ai_provider: str,
    text_model: str = "",
) -> str:
    """
    当文案过长时，先用 LLM 压缩为摘要，再用于文章生成。

    Args:
        transcript: 原始长文案
        api_key: API Key
        ai_provider: 服务商
        text_model: 模型名称

    Returns:
        压缩后的摘要文本
    """
    logger.info(f"[Step4/压缩] 文案过长 ({len(transcript)} 字符)，开始压缩")
    COMPRESSION_SYSTEM_PROMPT = "请将以下视频文案压缩为 2000 字以内的摘要，保留核心观点、关键数据和重要细节，不要添加任何自己的评论。"
    summary = _call_llm(
        system_prompt=COMPRESSION_SYSTEM_PROMPT,
        user_message=f"请压缩以下文案：\n\n{transcript}",
        max_tokens=1024,
        temperature=0.3,
        api_key=api_key,
        ai_provider=ai_provider,
        text_model=text_model,
    )
    result = summary.strip() or transcript[:4000]
    logger.info(f"[Step4/压缩] 完成 | 压缩后长度={len(result)}")
    return result


# =============================================================================
# 常量 — 质量检查
# =============================================================================

# 文案超过此字符数时先压缩再生成文章
TRANSCRIPT_COMPRESS_THRESHOLD = 5000


def _remove_duplicated_title_line(markdown_text: str, title: str) -> str:
    """如果正文第一行重复了 title 字段，剥离这一行。"""
    if not markdown_text or not title:
        return markdown_text

    lines = markdown_text.split("\n", 1)
    first_line = lines[0].strip()
    normalized_first = re.sub(r"^#{1,6}\s+", "", first_line).strip()
    normalized_first = normalized_first.strip("*_` ")
    normalized_title = title.strip()

    if normalized_first == normalized_title or normalized_title in normalized_first:
        return lines[1].strip() if len(lines) > 1 else ""
    return markdown_text


def _downgrade_markdown_headings(markdown_text: str) -> str:
    """把正文里的 Markdown 标题降级成加粗短语，代码块内不处理。"""
    lines: list[str] = []
    in_code_block = False

    for line in markdown_text.splitlines():
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            lines.append(line)
            continue

        if not in_code_block:
            match = re.match(r"^(\s*)#{1,6}\s+(.+?)\s*$", line)
            if match:
                indent, heading_text = match.groups()
                line = f"{indent}**{heading_text.strip()}**"

        lines.append(line)

    return "\n".join(lines)

# =============================================================================
# Function Calling 工具定义
# =============================================================================

ARTICLE_TOOL_WITH_IMAGE = {
    "type": "function",
    "function": {
        "name": "publish_markdown_article",
        "description": "将文章结构化输出，使用 Markdown 格式，供最终发布使用",
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
                        "不要在正文中插入任何图片占位符，正文只包含纯文字 Markdown。"
                        "标题只放在 title 字段，正文不要使用 #、##、### 这类标题。"
                        "不要写目录，不要套固定小节数量。"
                        "按问题、现象、分析、方法、结论线性推进，最多用 **加粗短语** 做段落锚点。"
                        "如果原始文案包含操作步骤、配置流程、命令或工具使用方法，必须把实操细节写具体。"
                        "语言口语化、短句为主，段落之间空一行。"
                        "需要列表或代码时再使用 Markdown 列表和 ```语言名\\n代码内容``` 代码块。"
                    ),
                },
                "image_prompts": {
                    "type": "array",
                    "description": (
                        "封面图的图片提示词数组。必须返回一个包含至少一个元素的数组，"
                        "第一个元素的 id 为 cover，prompt 为英文生图描述（50 词以内），突出文章主题和科技感。"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "占位符 ID，封面图固定为 cover",
                            },
                            "prompt": {
                                "type": "string",
                                "description": "英文 AI 生图 prompt，请根据文章主题生成专业的描述（50 词以内），需要突出主题和科技感",
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

ARTICLE_TOOL_WITHOUT_IMAGE = {
    "type": "function",
    "function": {
        "name": "publish_markdown_article",
        "description": "将文章结构化输出，使用 Markdown 格式，供最终发布使用",
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
                        "不要在正文中插入任何图片占位符，正文只包含纯文字 Markdown。"
                        "标题只放在 title 字段，正文不要使用 #、##、### 这类标题。"
                        "不要写目录，不要套固定小节数量。"
                        "按问题、现象、分析、方法、结论线性推进，最多用 **加粗短语** 做段落锚点。"
                        "如果原始文案包含操作步骤、配置流程、命令或工具使用方法，必须把实操细节写具体。"
                        "语言口语化、短句为主，段落之间空一行。"
                        "需要列表或代码时再使用 Markdown 列表和 ```语言名\\n代码内容``` 代码块。"
                    ),
                },
            },
            "required": ["title", "content"],
        },
    },
}


# =============================================================================
# System Prompt：融合  + Function Calling
# =============================================================================

SYSTEM_PROMPT_WRITER = """你是一个技术博主，为有实际经验的技术从业者写作。

你必须调用 publish_markdown_article 工具来输出结果，不要输出任何其他文字。

---

## 写作者身份
- 你是一个真实写代码、排查问题、踩过坑的技术人
- 不是讲师，不是产品经理，不是知识付费作者
- 说话方式像"我跟你聊这个坑"，不是"我来系统讲解"
- 观点来自场景和实操，不靠权威背书

## 文章主线
- 按线性叙事推进：问题 → 现象 → 分析 → 方法 → 结论
- 不写大标题，不写目录，不套固定小节数量
- 不强行规定几段、几个标题、几个方法，按素材信息量自然展开
- 开头直接切入问题或场景，不铺垫背景，不解释"本文将要讲什么"
- 结尾只用一句话点题，停住，不总结不升华不喊口号

## 开头方式
- 第一段就让读者进入具体处境
- 可以用"你肯定遇到过这种情况"这类共情场景
- 不要先定义概念，不要先讲行业背景，不要先摆大道理
- 三句话内让读者感觉"这说的是我"

## 语言风格
- 全程口语化，短句为主，句子允许不写完整
- 用破折号制造停顿，不用分号
- 用词接地气，可以用"玄"、"上头"、"加戏"、"自我感动"这类口语词
- 禁止出现：首先、其次、最后、综上所述、值得注意的是、不难发现、总而言之、由此可见
- 禁止书面套话、论文腔、培训课口吻

## Markdown 格式
- title 字段放文章标题，content 正文里不要再写标题
- 正文禁止使用 #、##、### 这类 Markdown 标题
- 最多用 **加粗短语** 做段落锚点，比如 **卡住的地方**、**问题就出在这**
- 段落之间空一行，保持短段落
- 需要操作步骤时再用列表，不要为了显得有结构强行列点
- 需要代码或命令时直接给代码块，不加"下面是代码"这类废话

## 论证方式
- 不引权威，不堆数据
- 用读者熟悉的故障、报错、配置、上线、调试场景推动观点
- 观点藏在场景里，不直接说教
- 分析必须落到"为什么会这样"和"怎么处理"上
- 方法部分讲清可执行动作，不绕

## 实操步骤
- 如果【原始文案】里有操作步骤、配置流程、命令、参数、工具使用方法，就把实操写具体
- 具体到读者能跟着做：点哪里、改哪个配置、跑什么命令、看什么现象、怎么判断成功
- 原始文案没给出的关键细节，不要硬编；可以用"这里要按你的环境改"这种说法兜住
- 如果只是观点类内容，没有明确操作步骤，不要为了显得实用强行加教程
- 步骤可以用列表，但每一步都要有动作，不写空泛建议

## 比喻和引用
- 不使用古诗词、名言金句、鸡汤式引用
- 不为了显得高级乱用比喻
- 如果确实需要类比，只能一句带过，马上回到技术场景和操作
- 不写玄学化表达，除非是在吐槽问题看起来很玄

## 克制原则
- 能用100字说清的，不写150字
- 每一段都要往前推进，不重复，不凑字数
- 不要为了满足格式而加戏
- 不要自我感动，不要写金句收尾
- 文章讲什么道理，行文本身就要践行那个道理
- 字数跟【原始文案】的信息量匹配，不强行扩写

## 知识融合规则

你收到的输入可能包含两部分：

1. **【原始文案】**：本文的核心素材来源。文章主线必须基于原始文案展开，不得脱离其主题。
2. **【参考知识】**：外部知识库的相关内容，只用于补充背景、校准判断、增加实操细节。

处理参考知识时遵守：
- 自然编进正文，不单独列出"参考知识"段落
- 不把参考知识写成资料摘抄
- 如果参考知识与原始文案冲突，以原始文案为主
- 如果参考知识为空，完全依靠原始文案创作，不要编造

最终文章应该像一个技术人把坑讲明白：有场景，有判断，有方法，有收束，但不摆架子。

输出方式：调用 publish_markdown_article 工具，将 title、content（Markdown 正文）、image_prompts 分别填入对应参数。"""


def _parse_tool_call_result(response) -> dict:
    """
    从 Function Calling 响应中解析出工具参数 JSON。
    兼容两种情况：
      1. 模型正确调用了工具（tool_calls）
      2. 模型不支持 Function Calling，回退到正文中提取 JSON
    """
    # 优先从 tool_calls 中提取
    msg = response.choices[0].message
    
    if msg.tool_calls:
        for tc in msg.tool_calls:
            if tc.function.name == "publish_markdown_article":
                args = json.loads(tc.function.arguments)
                logger.info(f"[_parse_tool_call_result] parsed from tool_calls, image_prompts len={len(args.get('image_prompts', []))}")
                return args

    # 回退：从文本内容中提取 JSON
    content = (msg.content or "").strip()
    logger.info(f"[_parse_tool_call_result] fallback to content parsing, content length={len(content)}")
    
    # 去掉 markdown 代码块
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(
            line for line in lines
            if not line.startswith("```")
        ).strip()
    try:
        result = json.loads(content)
        logger.info(f"[_parse_tool_call_result] parsed from content, image_prompts len={len(result.get('image_prompts', []))}")
        return result
    except json.JSONDecodeError:
        # 最后兜底：尝试找第一个 { ... } 块
        start = content.find("{")
        end = content.rfind("}") + 1
        if start != -1 and end > start:
            result = json.loads(content[start:end])
            logger.info(f"[_parse_tool_call_result] parsed from bracket extraction, image_prompts len={len(result.get('image_prompts', []))}")
            return result
        raise ValueError(
            "模型未调用工具且响应不含合法 JSON，请检查模型是否支持 Function Calling。\n"
            f"原始响应：{content[:300]}"
        )


# =============================================================================
# 对外接口
# =============================================================================


def create_content_task(
    pipeline_job_id: str,
    transcript: str,
    rag_collection: str | None = None,
    rag_top_k: int | None = None,
    rag_embedding_model: str | None = None,
    rag_embedding_provider: str | None = None,
    rag_embedding_api_key: str | None = None,
) -> str:
    """
    在 MySQL 中创建一条 content_task 记录，返回 task_id。

    Args:
        pipeline_job_id: 关联的 pipeline 任务 ID
        transcript: 原始转写文本
        rag_collection: 可选的 RAG 知识库集合名称
        rag_embedding_model: 用户选择的向量模型名，留空使用 config 默认值
        rag_embedding_provider: 向量模型服务商，留空使用 config 默认值
        rag_embedding_api_key: 向量模型专用 API Key，留空使用主 api_key

    Returns:
        task_id: 新创建的任务 UUID
    """
    task_id = str(uuid.uuid4())
    with get_db_ctx() as db:
        task = ContentTaskModel(
            task_id=task_id,
            pipeline_job_id=pipeline_job_id,
            status="pending",
            raw_transcript=transcript,
            rag_collection=rag_collection or "",
            rag_top_k=rag_top_k or get_settings().rag_top_k,
            rag_embedding_model=rag_embedding_model or None,
            rag_embedding_provider=rag_embedding_provider or None,
            rag_embedding_api_key=rag_embedding_api_key or None,
        )
        db.add(task)
        db.flush()
    logger.info(f"[Step4] 创建任务 | task_id={task_id} | pipeline_job_id={pipeline_job_id}")
    return task_id


def get_content_task(task_id: str) -> dict | None:
    """
    查询 content_task 的当前状态和结果。
    """
    with get_db_ctx() as db:
        task = db.scalar(
            select(ContentTaskModel).where(ContentTaskModel.task_id == task_id)
        )
        if not task:
            return None
        return {
            "task_id": task.task_id,
            "status": task.status,
            "rag_collection": task.rag_collection or "",
            "rag_top_k": task.rag_top_k or get_settings().rag_top_k,
            "rag_embedding_model": task.rag_embedding_model or "",
            "rag_embedding_provider": task.rag_embedding_provider or "",
            "rag_embedding_api_key": task.rag_embedding_api_key or "",
            "article_title": task.article_title or "",
            "article_final": task.article_final or "",
            "image_prompt": task.image_prompt or "",
            "knowledge_context": task.knowledge_context or "",
            "error": task.error or "",
            "raw_transcript": task.raw_transcript or "",
        }


# =============================================================================
# 核心文章生成
# =============================================================================


def _generate_article(
    task_id: str,
    transcript: str,
    api_key: str,
    ai_provider: str,
    text_model: str = "",
    image_provider: str = "",
    image_model: str = "",
    skip_image_generation: bool = False,
) -> tuple[str, str]:
    """
    核心文章生成逻辑（Function Calling 版）：
    1. 检索 RAG 知识
    2. 如果文案过长（>5k 字符），先用 LLM 压缩为摘要
    3. 构造 prompt，通过 Function Calling 调用 LLM 生成结构化文章
    4. 解析标题、回写 MySQL

    Args:
        task_id: 任务ID
        transcript: 转写文本
        api_key: API密钥
        ai_provider: AI服务商
        text_model: 文本模型名称
        image_provider: 图片生成服务商
        image_model: 图片生成模型
        skip_image_generation: 是否跳过图片生成（前端配置）

    Returns:
        (article_content, image_prompt)
    """
    # ── 1. 知识检索 ──
    logger.info(f"[Step4] 开始知识检索 | task_id={task_id}")
    knowledge_context = _retrieve_knowledge(transcript, task_id, api_key)

    # 回写检索结果
    _update_task(
        task_id,
        status="processing",
        knowledge_context=knowledge_context[:5000] if knowledge_context else None,
    )
    logger.info(f"[Step4] 知识检索完成 | task_id={task_id} | 知识长度={len(knowledge_context)}")

    # ── 1.5 文案压缩（过长时）────────────────────────────────────────
    if transcript and len(transcript) > TRANSCRIPT_COMPRESS_THRESHOLD:
        transcript = _compress_transcript(transcript, api_key, ai_provider, text_model=text_model)
        _update_task(task_id, raw_transcript=transcript[:5000])

    # ── 2. 构造输入 ──
    has_transcript = bool(transcript and transcript.strip())
    has_knowledge = bool(knowledge_context and knowledge_context.strip())

    transcript_part = transcript if has_transcript else "（无原始文案）"

    if has_knowledge:
        knowledge_part = knowledge_context[:3000]
        user_message = (
            f"请根据以下素材创作一篇完整的公众号文章。\n\n"
            f"# 【原始文案】\n{transcript_part}\n\n"
            f"# 【参考知识（用于提升深度）】\n{knowledge_part}\n\n"
            f"要求：将参考知识自然融入文章正文中，"
            f"用来佐证观点、补充背景或引用行业经典，"
            f"不要单独列出『参考知识』段落。"
        )
    else:
        user_message = (
            f"请根据以下素材创作一篇完整的公众号文章。\n\n"
            f"# 【原始文案】\n{transcript_part}"
        )

    # ── 3. 获取模型配置 ──
    config = get_settings()
    ai_cfg = config.get_ai_provider_config(ai_provider)
    model = text_model or ai_cfg.get("default_text_model", "Qwen/Qwen3-14B")
    temperature = config.siliconflow_default_temperature
    max_tokens = config.siliconflow_max_tokens

    # ── 4. 创建 Client ──
    client = _get_llm_client(api_key, ai_provider)

    # ── 5. 调用 LLM（Function Calling） ──
    logger.info(f"[Step4] 调用 LLM 生成文章 | task_id={task_id} | model={model}")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_WRITER},
        {"role": "user", "content": user_message},
    ]

    # 根据前端配置选择工具定义
    if skip_image_generation:
        logger.info("[Step4] 跳过图片生成，使用 ARTICLE_TOOL_WITHOUT_IMAGE")
        tool_def = ARTICLE_TOOL_WITHOUT_IMAGE
    else:
        logger.info("[Step4] 启用图片生成，使用 ARTICLE_TOOL_WITH_IMAGE")
        tool_def = ARTICLE_TOOL_WITH_IMAGE

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=[tool_def],
        tool_choice={"type": "function", "function": {"name": "publish_markdown_article"}},
        temperature=temperature,
        max_tokens=max_tokens,
    )

    article_data = _parse_tool_call_result(response)

    # ── 6. 解析结果 ──
    article_data.setdefault("title", "AI生成文章")
    article_data.setdefault("content", "")
    if not skip_image_generation:
        article_data.setdefault("image_prompts", [])

    title = article_data["title"]
    final_article = article_data["content"].strip()

    # ── 7. 提取封面图提示词 ──
    # 如果前端配置跳过图片生成，则直接返回空
    if skip_image_generation:
        logger.info(f"[_generate_article] skip_image_generation=True，跳过图片提示词提取")
        cover_prompt = None
    else:
        # 从 LLM 返回的 image_prompts 数组中提取第一个（id=cover）的 prompt
        cover_prompt = None
        raw_prompts = article_data.get("image_prompts", [])
        
        if raw_prompts and isinstance(raw_prompts, list) and len(raw_prompts) > 0:
            first = raw_prompts[0]
            if isinstance(first, dict):
                cover_prompt = first.get("prompt", "") or None
            elif isinstance(first, str):
                cover_prompt = first
        # 兜底：如果 LLM 直接返回了 image_prompt 字段
        if not cover_prompt and article_data.get("image_prompt"):
            cover_prompt = article_data["image_prompt"]
        
        logger.info(f"[_generate_article] final cover_prompt: {cover_prompt}")

    # 强制剥离任何残留的图片占位符（即使 LLM 未完全听从指令）
    final_article = re.sub(
        r'【图片占位符[：:]\s*[A-Za-z0-9_]+\s*】\n*',
        '',
        final_article
    ).strip()

    # 安全兜底：正文不重复 title，不保留 #/##/### 标题形态
    final_article = _remove_duplicated_title_line(final_article, title)
    final_article = _downgrade_markdown_headings(final_article).strip()

    if not final_article:
        raise ValueError("LLM 返回的文章内容为空，请重试（模型可能已崩溃）")

    logger.info(
        f"[Step4] 文章生成完成 | "
        f"标题={title[:30]} | "
        f"字数={len(final_article)}"
    )

    # ── 8. 回写 MySQL ──
    _update_task(
        task_id,
        status="completed",
        article_final=final_article or None,
        article_title=title,
        image_prompt=cover_prompt,
    )

    return final_article, cover_prompt


# =============================================================================
# Pipeline 入口
# =============================================================================


def run_step4_pipeline(
    task_id: str,
    transcript: str,
    api_key: str = "",
    ai_provider: str = "siliconflow",
    text_model: str = "",
    image_provider: str = "",
    image_model: str = "",
    skip_image_generation: bool = False,
) -> dict:
    """
    执行 Step 4 文章生成流水线（同步，在后台线程中调用）。

    Args:
        task_id: 由 create_content_task() 创建的 task_id
        transcript: 原始转写文本
        api_key: AI 服务 API Key，用于 LLM 调用和 RAG 向量检索
        ai_provider: 服务商名 ("siliconflow" | "zhipu")
        text_model: 前端选择的模型名称（优先），为空则从配置读取
        image_provider: 图片生成服务商
        image_model: 图片生成模型
        skip_image_generation: 是否跳过图片生成（前端配置）
    
    Returns:
        {
            "task_id": str,
            "status": "completed" | "failed",
            "article_title": str,
            "article_final": str,
            "image_prompt": str | None,
            "error": str | None,
        }
    """
    logger.info(
        f"[Step4/pipeline] 启动 | task_id={task_id} | 转录文本长度={len(transcript)} | skip_image={skip_image_generation}"
    )

    try:
        final_article, image_prompt = _generate_article(
            task_id=task_id,
            transcript=transcript,
            api_key=api_key,
            ai_provider=ai_provider,
            text_model=text_model,
            image_provider=image_provider,
            image_model=image_model,
            skip_image_generation=skip_image_generation,
        )

        if not final_article or not final_article.strip():
            raise ValueError("LLM 返回的文章内容为空，请检查模型输出或重试")

        logger.info(f"[Step4/pipeline] 执行完成 | task_id={task_id}")

        # 从 DB 读取最终结果（保证状态已持久化）
        task = get_content_task(task_id)
        if task:
            return {
                "task_id": task_id,
                "status": "completed",
                "article_title": task.get("article_title", "AI生成文章"),
                "article_final": task.get("article_final", ""),
                "image_prompt": task.get("image_prompt", ""),
                "error": None,
            }
        else:
            return {
                "task_id": task_id,
                "status": "completed",
                "article_title": "AI生成文章",
                "article_final": final_article,
                "image_prompt": image_prompt,
                "error": None,
            }

    except Exception as e:
        logger.exception(f"[Step4/pipeline] 执行失败 | task_id={task_id} | 错误={e}")
        _update_task(
            task_id,
            status="failed",
            error=str(e),
        )
        return {
            "task_id": task_id,
            "status": "failed",
            "article_title": "",
            "article_final": "",
            "image_prompt": "",
            "error": str(e),
        }
