from __future__ import annotations

import hashlib
from pathlib import Path

from playwright.async_api import Error, Page

from article_to_speech.browser.capture import extension_from_audio
from article_to_speech.infra.audio import write_audio_bytes, write_base64_audio


def _audio_output_path(
    chunk_dir: Path,
    audio_source: dict[str, str],
    stem: str = "chatgpt-audio",
) -> Path:
    if audio_source["format"] == "mp3":
        extension = ".mp3"
    elif audio_source["format"] == "m4a":
        extension = ".m4a"
    else:
        extension = ".webm"
    return chunk_dir / f"{stem}{extension}"


async def _download_audio_sources(
    page: Page, chunk_dir: Path, sources: list[dict[str, str]]
) -> list[Path]:
    paths: list[Path] = []
    seen_urls: set[str] = set()
    for index, source in enumerate(sources, start=1):
        url = source["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        stem = "chatgpt-audio" if len(sources) == 1 else f"chatgpt-audio-{index:02d}"
        output_path = _audio_output_path(chunk_dir, source, stem)
        if url.startswith("blob:"):
            try:
                payload = await page.evaluate(
                    """
                    async sourceUrl => {
                        const response = await fetch(sourceUrl);
                        const buffer = await response.arrayBuffer();
                        const bytes = new Uint8Array(buffer);
                        let binary = "";
                        for (const value of bytes) {
                            binary += String.fromCharCode(value);
                        }
                        return btoa(binary);
                    }
                    """,
                    url,
                )
            except Error:
                continue
            if isinstance(payload, str) and payload:
                paths.append(write_base64_audio(output_path, payload, "browser_blob").path)
            continue
        try:
            response = await page.context.request.get(url)
        except Error:
            continue
        if not response.ok:
            continue
        payload = await response.body()
        if not payload:
            continue
        write_audio_bytes(output_path, payload)
        paths.append(output_path)
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
