from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
import shutil
import subprocess
from pathlib import Path

from article_to_speech.core.models import AudioArtifact


def write_audio_bytes(
    output_path: Path,
    payload: bytes,
    *,
    source_method: str = "network",
) -> AudioArtifact:
    """Persist raw audio bytes and return the corresponding artifact metadata."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    return _build_artifact(output_path, payload, source_method)


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


def artifact_dir(root: Path, title: str, source_url: str | None = None) -> Path:
    """Return a stable artifact subdirectory for the given article title."""
    directory = root / artifact_stem(title, source_url)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def artifact_file_name(title: str, source_url: str | None, extension: str) -> str:
    """Return a descriptive artifact file name for the given article."""
    normalized_extension = extension if extension.startswith(".") else f".{extension}"
    return f"{artifact_stem(title, source_url)}{normalized_extension}"


def build_final_artifact(
    title: str,
    artifacts_dir: Path,
    chunk_outputs: list[Path],
    source_url: str | None = None,
) -> AudioArtifact:
    """Assemble the final article artifact from one or more MP3 chunks."""
    if not chunk_outputs:
        raise ValueError("No audio chunks were produced for synthesis.")
    output_dir = artifact_dir(artifacts_dir, title, source_url)
    output_path = output_dir / artifact_file_name(title, source_url, ".mp3")
    if len(chunk_outputs) == 1:
        if chunk_outputs[0].resolve() != output_path.resolve():
            shutil.copyfile(chunk_outputs[0], output_path)
        return _build_artifact(output_path, output_path.read_bytes(), "single_chunk")
    return concat_mp3_files(chunk_outputs, output_path)


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


def artifact_stem(title: str, source_url: str | None = None) -> str:
    """Return a stable stem for article artifacts."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower() or "article"
    snapshot_id = _archive_snapshot_id(source_url)
    if snapshot_id:
        return f"{slug}-{snapshot_id}"
    return slug


def _archive_snapshot_id(source_url: str | None) -> str | None:
    if not source_url:
        return None
    match = re.search(r"archive\.(?:is|ph|today)/([A-Za-z0-9]+)", source_url)
    if match is None:
        return None
    return match.group(1).lower()
