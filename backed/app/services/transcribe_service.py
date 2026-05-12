"""
语音转写服务
业务逻辑来自 transcribe_audio_auto.py，完全保留
"""
from __future__ import annotations

import importlib
from pathlib import Path

from app.core.config import get_settings


def _resolve_device(device: str) -> tuple[str, str]:
    """
    将 device/compute_type 解析为 faster-whisper 实际使用的值。

    Args:
        device: "auto" / "cpu" / "cuda"

    Returns:
        (resolved_device, resolved_compute_type)
    """
    if device == "auto":
        try:
            import torch
            if torch.cuda.is_available():
                print(f"[Whisper] 检测到 GPU: {torch.cuda.get_device_name(0)}，使用 CUDA + float16")
                return "cuda", "float16"
        except ImportError:
            pass
        print("[Whisper] 未检测到 GPU，使用 CPU + int8")
        return "cpu", "int8"

    # 显式指定设备时，compute_type 交给调用方或 config 决定
    compute_type_map = {"cuda": "float16", "cpu": "int8"}
    return device, compute_type_map.get(device, "int8")


def _ensure_faster_whisper():
    try:
        return importlib.import_module("faster_whisper")
    except ImportError:
        raise ImportError("未检测到依赖 faster-whisper；请先执行 pip install -r requirements.txt")


def transcribe_audio(
    audio_path: Path,
    output_path: Path,
    model_size: str | None = None,
    language: str | None = None,
    device: str | None = None,
    compute_type: str | None = None,
) -> str:
    """
    将音频文件转写为文字，写入 output_path，返回转写文本
    业务逻辑完全来自 transcribe_audio_auto.py

    Args:
        audio_path: 音频文件路径
        output_path: 转写结果输出路径
        model_size: 模型大小（tiny/base/small/medium/large-v3）
        language: 语言代码（zh/en/ja/...）
        device: 设备（auto/cpu/cuda），覆盖 config.yaml
        compute_type: 计算精度（auto/int8/float16），覆盖 config.yaml
    """
    cfg = get_settings()
    if model_size is None:
        model_size = cfg.transcribe_default_model
    if language is None:
        language = cfg.transcribe_default_language

    # 解析设备：请求参数 > config.yaml > 自动检测
    raw_device = device or cfg.transcribe_device
    if compute_type and compute_type != "auto":
        # 调用方显式指定了 compute_type，device 也一并确认
        resolved_device = raw_device if raw_device != "auto" else (_resolve_device("auto")[0])
        resolved_compute_type = compute_type
    else:
        resolved_device, resolved_compute_type = _resolve_device(raw_device)

    if not audio_path.exists():
        raise FileNotFoundError(f"音频文件不存在: {audio_path}")

    faster_whisper = _ensure_faster_whisper()
    WhisperModel = faster_whisper.WhisperModel

    print(f"正在加载模型: {model_size}  device={resolved_device}  compute_type={resolved_compute_type}")
    print("如果是第一次运行，会自动下载模型，请耐心等待...")

    model = WhisperModel(
        model_size,
        device=resolved_device,
        compute_type=resolved_compute_type,
    )

    print(f"开始转写: {audio_path}")
    segments, info = model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=cfg.transcribe_vad_filter,
    )

    lines = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            lines.append(text)

    result = "\n".join(lines).strip()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result, encoding="utf-8")

    print(f"检测语言: {info.language}")
    print(f"转写完成，已保存到: {output_path}")
    return result
