"""
音频提取服务
业务逻辑来自 yinpin.py，完全保留
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from app.core.config import get_settings


def _ensure_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        print("未找到 ffmpeg，正在自动安装 imageio-ffmpeg ...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "imageio-ffmpeg"],
            check=True,
        )
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()


def _build_output_path(video_path: Path, audio_format: str) -> Path:
    return video_path.with_suffix(f".{audio_format}")


def _build_ffmpeg_command(
    ffmpeg: str, video_path: Path, output_path: Path, audio_format: str
) -> list[str]:
    cfg = get_settings()
    if audio_format == "mp3":
        return [
            ffmpeg, "-y",
            "-i", str(video_path),
            "-vn",
            "-acodec", "libmp3lame",
            "-q:a", cfg.audio_ffmpeg_mp3_quality,
            str(output_path),
        ]
    if audio_format == "wav":
        return [
            ffmpeg, "-y",
            "-i", str(video_path),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            "-ac", "2",
            str(output_path),
        ]
    raise ValueError(f"不支持的音频格式: {audio_format}")


def extract_audio(
    video_path: Path,
    output_path: Path | None = None,
    audio_format: str | None = None,
) -> Path:
    """
    从视频提取音频，返回音频文件路径
    业务逻辑完全来自 yinpin.py
    """
    cfg = get_settings()
    if audio_format is None:
        audio_format = cfg.audio_default_format

    if not video_path.exists():
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    ffmpeg = _ensure_ffmpeg()

    if output_path is None:
        output_path = _build_output_path(video_path, audio_format)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = _build_ffmpeg_command(ffmpeg, video_path, output_path, audio_format)
    subprocess.run(cmd, check=True, capture_output=True)

    print(f"音频已导出到: {output_path}")
    return output_path
