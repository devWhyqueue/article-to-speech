from __future__ import annotations

from pathlib import Path

from playwright.async_api import Error, Page

from article_to_speech.infra.audio import write_audio_bytes, write_base64_audio
from article_to_speech.infra.browser_audio_runtime import _record_played_audio_blob


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
            payload = await _record_played_audio_blob(page)
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
