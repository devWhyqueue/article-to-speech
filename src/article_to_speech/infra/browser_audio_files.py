from __future__ import annotations

import hashlib
from pathlib import Path

from playwright.async_api import Page

from article_to_speech.browser.capture import extension_from_audio
from article_to_speech.infra.audio import write_audio_bytes


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


async def _wait_for_audio_response_payload(
    page: Page,
    response_payloads: list[tuple[str, str, bytes]],
    *,
    timeout_ms: int = 30_000,
) -> None:
    waited_ms = 0
    while waited_ms < timeout_ms:
        if response_payloads:
            return
        await page.wait_for_timeout(500)
        waited_ms += 500
    raise TimeoutError("Timed out waiting for the ChatGPT synthesize response.")
