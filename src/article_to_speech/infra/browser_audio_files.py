from __future__ import annotations

import hashlib
from pathlib import Path

from article_to_speech.browser.capture import extension_from_audio
from article_to_speech.infra.audio import write_audio_bytes, write_base64_audio


def _write_direct_audio(
    chunk_dir: Path,
    direct_audio: dict[str, str],
    stem: str = "chatgpt-audio",
) -> Path:
    if direct_audio["format"] == "mp3":
        extension = ".mp3"
    elif direct_audio["format"] == "m4a":
        extension = ".m4a"
    else:
        extension = ".webm"
    output_path = chunk_dir / f"{stem}{extension}"
    return write_base64_audio(output_path, direct_audio["payload"], "browser_state").path


def _write_direct_segments(chunk_dir: Path, segments: list[dict[str, str]]) -> list[Path]:
    paths: list[Path] = []
    for index, segment in enumerate(segments, start=1):
        stem = "chatgpt-audio" if len(segments) == 1 else f"chatgpt-audio-{index:02d}"
        paths.append(_write_direct_audio(chunk_dir, segment, stem))
    return paths


def _write_network_payloads(
    chunk_dir: Path,
    response_payloads: list[tuple[str, str, bytes]],
) -> list[Path]:
    paths: list[Path] = []
    seen_payloads: set[str] = set()
    for index, (url, content_type, payload) in enumerate(response_payloads, start=1):
        if not payload:
            continue
        digest = hashlib.sha256(payload).hexdigest()
        if digest in seen_payloads:
            continue
        seen_payloads.add(digest)
        stem = "network-audio" if len(response_payloads) == 1 else f"network-audio-{index:02d}"
        output_path = chunk_dir / f"{stem}{extension_from_audio(url, content_type)}"
        write_audio_bytes(output_path, payload)
        paths.append(output_path)
    return paths
