from __future__ import annotations

import hashlib
from pathlib import Path

from playwright.async_api import Page

from article_to_speech.browser.capture import extension_from_audio
from article_to_speech.infra.audio import probe_audio_duration_seconds, write_audio_bytes

_NEXT_AUDIO_CHUNK_TIMEOUT_MS = 360_000
_CHATGPT_CHUNK_TARGET_SECONDS = 300.0
_CHATGPT_CHUNK_TOLERANCE_SECONDS = 3.0


def _write_network_payloads(
    chunk_dir: Path,
    response_payloads: list[tuple[str, str, bytes]],
    *,
    start_index: int = 1,
) -> list[Path]:
    paths: list[Path] = []
    seen_payloads: set[str] = set()
    for index, (url, content_type, payload) in enumerate(response_payloads, start=start_index):
        if not payload:
            continue
        digest = hashlib.sha256(payload).hexdigest()
        if digest in seen_payloads:
            continue
        seen_payloads.add(digest)
        stem = (
            "network-audio"
            if len(response_payloads) == 1 and start_index == 1
            else f"network-audio-{index:02d}"
        )
        output_path = chunk_dir / f"{stem}{extension_from_audio(url, content_type)}"
        write_audio_bytes(output_path, payload)
        paths.append(output_path)
    return paths


async def _wait_for_audio_response_payload(
    page: Page,
    response_payloads: list[tuple[str, str, bytes]],
    *,
    timeout_ms: int = 30_000,
    minimum_payload_count: int = 1,
) -> None:
    waited_ms = 0
    while waited_ms < timeout_ms:
        if len(response_payloads) >= minimum_payload_count:
            return
        await page.wait_for_timeout(500)
        waited_ms += 500
    raise TimeoutError("Timed out waiting for the ChatGPT synthesize response.")


async def capture_audio_payload_paths(
    page: Page,
    response_payloads: list[tuple[str, str, bytes]],
    chunk_dir: Path,
) -> list[Path]:
    written_paths: list[Path] = []
    processed_payload_count = 0
    while True:
        new_payloads = response_payloads[processed_payload_count:]
        if new_payloads:
            written_paths.extend(
                _write_network_payloads(
                    chunk_dir,
                    new_payloads,
                    start_index=len(written_paths) + 1,
                )
            )
            processed_payload_count = len(response_payloads)
        if not written_paths:
            return []
        latest_duration = probe_audio_duration_seconds(written_paths[-1])
        if not _looks_like_full_sized_chatgpt_chunk(latest_duration):
            return written_paths
        expected_payload_count = processed_payload_count + 1
        try:
            await _wait_for_audio_response_payload(
                page,
                response_payloads,
                timeout_ms=_NEXT_AUDIO_CHUNK_TIMEOUT_MS,
                minimum_payload_count=expected_payload_count,
            )
        except TimeoutError:
            return written_paths


def _looks_like_full_sized_chatgpt_chunk(duration_seconds: float | None) -> bool:
    if duration_seconds is None:
        return False
    return abs(duration_seconds - _CHATGPT_CHUNK_TARGET_SECONDS) <= _CHATGPT_CHUNK_TOLERANCE_SECONDS
