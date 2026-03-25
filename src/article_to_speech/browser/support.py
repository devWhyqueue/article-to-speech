from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Callable
from pathlib import Path

from playwright.async_api import BrowserContext, Page, Response

from article_to_speech.browser.capture import (
    artifact_dir,
    artifact_file_name,
    collect_browser_snapshot,
    maybe_capture_response_bytes,
    write_diagnostics,
)
from article_to_speech.browser.ui import (
    click_maybe,
    click_text,
    fill_first,
    locate_read_aloud_button,
)
from article_to_speech.core.exceptions import AuthenticationRequiredError, BrowserAutomationError
from article_to_speech.core.models import AudioArtifact, BrowserStepLog
from article_to_speech.infra.audio import concat_mp3_files, write_base64_audio
from article_to_speech.infra.browser_audio_files import (
    _write_direct_segments,
    _write_network_payloads,
)
from article_to_speech.infra.browser_audio_runtime import (
    _extract_audio_segments_from_page,
    _record_audio_stream,
    _wait_for_audio_completion,
)

LOGIN_TEXT_PATTERN = re.compile(
    r"\b(log in|sign up|continue with google|continue with apple)\b",
    re.I,
)
LOGGER = logging.getLogger(__name__)


async def ensure_authenticated(page: Page) -> None:
    """Validate that the persistent ChatGPT profile is already logged in."""
    await page.wait_for_timeout(2_000)
    title = await page.title()
    body_text = await page.locator("body").inner_text(timeout=10_000)
    if looks_like_challenge_page(title, body_text, page.url):
        raise AuthenticationRequiredError(
            "ChatGPT is presenting a Cloudflare or cookie challenge. "
            "Open the setup-browser desktop, complete the challenge in the persistent profile, "
            "then retry the automation."
        )
    if "login" in page.url or "auth" in page.url:
        raise AuthenticationRequiredError(
            "ChatGPT browser profile is not authenticated. "
            "Run the setup-browser flow and log in manually."
        )
    if LOGIN_TEXT_PATTERN.search(body_text):
        raise AuthenticationRequiredError(
            "ChatGPT browser profile appears logged out. "
            "Re-authenticate using the persistent profile."
        )


async def create_project(page: Page, project_name: str) -> None:
    """Create the target ChatGPT project when it does not already exist."""
    if not await click_text(page, "New project"):
        raise BrowserAutomationError(f"Unable to find or create ChatGPT project '{project_name}'.")
    await page.wait_for_timeout(1_000)
    filled = await fill_first(
        page,
        [
            "input[placeholder*='Project']",
            "input[name='name']",
            "input[type='text']",
        ],
        project_name,
    )
    if not filled:
        raise BrowserAutomationError(
            "Project creation dialog appeared but no project name input was found."
        )
    if not await click_text(page, "Create"):
        raise BrowserAutomationError("Failed to confirm ChatGPT project creation.")
    await page.wait_for_timeout(2_000)


async def get_or_create_page(context: BrowserContext) -> Page:
    """Reuse the first persistent page or open a new one."""
    return context.pages[0] if context.pages else await context.new_page()


async def submit_prompt(page: Page) -> None:
    """Submit the current ChatGPT composer contents."""
    if not await click_maybe(
        page,
        ["button[data-testid='send-button']", "button[aria-label*='Send']"],
    ):
        await page.keyboard.press("Enter")
    await page.wait_for_timeout(1_000)


def response_listener(
    response_payloads: list[tuple[str, str, bytes]],
    capture_tasks: list[asyncio.Task[None]],
) -> Callable[[Response], None]:
    """Create a response hook that captures audio-like payloads asynchronously."""

    def _listener(response: Response) -> None:
        task = asyncio.create_task(maybe_capture_response_bytes(response, response_payloads))
        capture_tasks.append(task)

    return _listener


def final_artifact(
    title: str,
    artifacts_dir: Path,
    chunk_outputs: list[Path],
    source_url: str | None = None,
) -> AudioArtifact:
    """Assemble the final article artifact from one or more MP3 chunks."""
    if not chunk_outputs:
        raise BrowserAutomationError("No audio chunks were captured from ChatGPT.")
    output_dir = artifact_dir(artifacts_dir, title, source_url)
    output_path = output_dir / artifact_file_name(title, source_url, ".mp3")
    if len(chunk_outputs) == 1:
        payload = chunk_outputs[0].read_bytes()
        output_path.write_bytes(payload)
        return AudioArtifact(
            path=output_path,
            mime_type="audio/mpeg",
            duration_seconds=None,
            source_method="single_chunk",
            sha256_hex=hashlib.sha256(payload).hexdigest(),
        )
    return concat_mp3_files(chunk_outputs, output_path)


def looks_like_challenge_page(title: str, body_text: str, url: str) -> bool:
    """Return whether the current page matches a Cloudflare or anti-bot challenge."""
    lowered = f"{title}\n{body_text}\n{url}".lower()
    markers = (
        "just a moment",
        "challenge-platform",
        "verification successful. waiting for chatgpt.com to respond",
        "enable javascript and cookies to continue",
        "cf_chl",
    )
    return any(marker in lowered for marker in markers)


async def capture_audio_chunk(
    *,
    page: Page,
    downloads: list,
    response_payloads: list[tuple[str, str, bytes]],
    diagnostics_dir: Path,
    chunk_index: int,
) -> list[Path]:
    """Capture one narrated audio chunk from the active assistant response."""
    downloads.clear()
    response_payloads.clear()
    assistant_turn = page.locator("section[data-turn='assistant']").last
    await assistant_turn.hover(timeout=10_000)
    read_aloud_button = await locate_read_aloud_button(assistant_turn, page)
    if read_aloud_button is None:
        raise BrowserAutomationError("Could not find the ChatGPT read-aloud control.")
    await read_aloud_button.click(timeout=10_000)
    chunk_dir = diagnostics_dir / f"chunk-{chunk_index:02d}"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    await _wait_for_audio_completion(page, response_payloads, downloads)
    direct_audio = await _extract_audio_segments_from_page(page)
    if direct_audio:
        return _write_direct_segments(chunk_dir, direct_audio)
    for download in downloads:
        suggested_name = download.suggested_filename or f"chunk-{chunk_index}.bin"
        download_path = chunk_dir / suggested_name
        await download.save_as(download_path)
    if downloads:
        return [
            chunk_dir / (download.suggested_filename or f"chunk-{chunk_index}.bin")
            for download in downloads
        ]
    network_paths = _write_network_payloads(chunk_dir, response_payloads)
    if network_paths:
        return network_paths
    recorded = await _record_audio_stream(page)
    if recorded:
        output_path = chunk_dir / "fallback-stream.webm"
        return [write_base64_audio(output_path, recorded, "capture_stream").path]
    raise BrowserAutomationError("Failed to capture any audio bytes from the ChatGPT browser flow.")


async def monitor_setup_challenge(page: Page, diagnostics_dir: Path) -> None:
    """Capture setup-browser diagnostics when ChatGPT stays on a challenge page."""
    wrote_snapshot = False
    while True:
        try:
            await page.wait_for_timeout(5_000)
            title = await page.title()
            body_text = await page.locator("body").inner_text(timeout=5_000)
            if not looks_like_challenge_page(title, body_text, page.url):
                continue
            if wrote_snapshot:
                continue
            wrote_snapshot = True
            snapshot = await collect_browser_snapshot(page)
            LOGGER.warning(
                "setup_browser_challenge_detected",
                extra={"context": {"snapshot": snapshot, "diagnostics_dir": str(diagnostics_dir)}},
            )
            await write_diagnostics(
                page,
                diagnostics_dir,
                [
                    BrowserStepLog(
                        step="setup_browser_challenge",
                        detail="Cloudflare challenge detected",
                    )
                ],
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001
            LOGGER.warning("setup_browser_monitor_failed", exc_info=error)
