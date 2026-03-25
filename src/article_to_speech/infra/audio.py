from __future__ import annotations

import base64
import hashlib
import mimetypes
import subprocess
from pathlib import Path

from article_to_speech.core.models import AudioArtifact


def write_audio_bytes(output_path: Path, payload: bytes) -> AudioArtifact:
    """Persist raw audio bytes and return the corresponding artifact metadata."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    return _build_artifact(output_path, payload, "network")


def write_base64_audio(output_path: Path, payload_base64: str, source_method: str) -> AudioArtifact:
    """Decode a base64 audio payload, write it to disk, and return artifact metadata."""
    raw_bytes = base64.b64decode(payload_base64)
    return _build_written_artifact(output_path, raw_bytes, source_method)


def convert_to_mp3(input_path: Path, output_path: Path) -> AudioArtifact:
    """Normalize any captured audio file into an MP3 suitable for Telegram delivery."""
    _run_ffmpeg(
        input_args=["-i", str(input_path)],
        output_path=output_path,
        codec_args=["-vn", "-acodec", "libmp3lame", "-b:a", "128k"],
    )
    return _build_artifact(output_path, output_path.read_bytes(), "converted")


def concat_mp3_files(input_paths: list[Path], output_path: Path) -> AudioArtifact:
    """Concatenate MP3 chunks into a single output artifact."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    concat_file = output_path.with_suffix(".txt")
    concat_file.write_text(
        "\n".join(f"file '{path.as_posix()}'" for path in input_paths),
        encoding="utf-8",
    )
    _run_ffmpeg(
        input_args=["-f", "concat", "-safe", "0", "-i", str(concat_file)],
        output_path=output_path,
        codec_args=["-c", "copy"],
    )
    concat_file.unlink(missing_ok=True)
    return _build_artifact(output_path, output_path.read_bytes(), "concat")


def _build_written_artifact(output_path: Path, payload: bytes, source_method: str) -> AudioArtifact:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    return _build_artifact(output_path, payload, source_method)


def _build_artifact(output_path: Path, payload: bytes, source_method: str) -> AudioArtifact:
    return AudioArtifact(
        path=output_path,
        mime_type=mimetypes.guess_type(output_path.name)[0] or "application/octet-stream",
        duration_seconds=None,
        source_method=source_method,
        sha256_hex=hashlib.sha256(payload).hexdigest(),
    )


def _run_ffmpeg(*, input_args: list[str], output_path: Path, codec_args: list[str]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", *input_args, *codec_args, str(output_path)],
        check=True,
        capture_output=True,
        text=True,
    )
