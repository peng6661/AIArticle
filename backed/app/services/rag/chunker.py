"""
文本分块器
将长文本按段落/句子边界切分为重叠的块，确保语义完整性。
"""
from __future__ import annotations

import re


def chunk_text(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 100,
) -> list[str]:
    """
    将文本切分为重叠的块。

    切分策略：
    1. 优先按段落（双换行）切分
    2. 段落过长时按句子切分
    3. 句子过长时按 chunk_size 硬切
    4. 相邻块之间保留 chunk_overlap 字符的重叠

    Args:
        text: 待切分的文本
        chunk_size: 每个块的目标字符数
        chunk_overlap: 块之间的重叠字符数

    Returns:
        分块后的文本列表
    """
    if not text or not text.strip():
        return []

    text = text.strip()

    # 如果文本本身就小于 chunk_size，直接返回
    if len(text) <= chunk_size:
        return [text]

    # 第一步：按段落切分
    paragraphs = re.split(r"\n{2,}", text)

    # 第二步：将段落组合为接近 chunk_size 的块
    chunks: list[str] = []
    current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # 如果当前块加上新段落不超过 chunk_size，合并
        if current_chunk and len(current_chunk) + len(para) + 2 <= chunk_size:
            current_chunk += "\n\n" + para
        elif not current_chunk:
            # 段落本身超过 chunk_size，需要进一步切分
            if len(para) > chunk_size:
                # 先保存当前块（如果有）
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""
                # 按句子切分长段落
                sub_chunks = _chunk_by_sentences(para, chunk_size)
                chunks.extend(sub_chunks)
            else:
                current_chunk = para
        else:
            # 当前块已满，保存并开始新块
            chunks.append(current_chunk)
            # 段落本身超过 chunk_size
            if len(para) > chunk_size:
                sub_chunks = _chunk_by_sentences(para, chunk_size)
                chunks.extend(sub_chunks)
                current_chunk = ""
            else:
                current_chunk = para

    if current_chunk:
        chunks.append(current_chunk)

    # 第三步：添加重叠
    if chunk_overlap > 0 and len(chunks) > 1:
        chunks = _add_overlap(chunks, chunk_overlap)

    return chunks


def _chunk_by_sentences(text: str, chunk_size: int) -> list[str]:
    """按句子边界切分长文本。"""
    # 中英文句子结束符
    sentences = re.split(r"(?<=[。！？；\n.!?;])\s*", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks: list[str] = []
    current = ""

    for sent in sentences:
        if current and len(current) + len(sent) + 1 <= chunk_size:
            current += " " + sent
        elif not current:
            # 单个句子超过 chunk_size，硬切
            if len(sent) > chunk_size:
                for i in range(0, len(sent), chunk_size):
                    chunks.append(sent[i:i + chunk_size])
            else:
                current = sent
        else:
            chunks.append(current)
            if len(sent) > chunk_size:
                for i in range(0, len(sent), chunk_size):
                    chunks.append(sent[i:i + chunk_size])
                current = ""
            else:
                current = sent

    if current:
        chunks.append(current)

    return chunks


def _add_overlap(chunks: list[str], overlap: int) -> list[str]:
    """为相邻块添加重叠内容。"""
    result = [chunks[0]]
    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        # 取前一个块的末尾 overlap 字符作为当前块的前缀
        overlap_text = prev[-overlap:]
        # 尝试在句子边界处截断重叠
        for sep in ["。", "！", "？", ".", "!", "?", "\n"]:
            idx = overlap_text.find(sep)
            if idx != -1 and idx > overlap // 3:
                overlap_text = overlap_text[idx + 1:]
                break
        result.append(overlap_text + chunks[i])
    return result
