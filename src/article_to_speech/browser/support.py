from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from playwright.async_api import BrowserContext, Download, Page

from article_to_speech.browser.capture import (
    artifact_dir,
    artifact_file_name,
    collect_browser_snapshot,
    write_diagnostics,
)
from article_to_speech.browser.ui import locate_read_aloud_button
from article_to_speech.core.exceptions import AuthenticationRequiredError, BrowserAutomationError
from article_to_speech.core.models import AudioArtifact, BrowserStepLog
from article_to_speech.infra.audio import concat_mp3_files
from article_to_speech.infra.browser_audio_files import (
    _wait_for_audio_response_payload,
    _write_network_payloads,
)

LOGIN_TEXT_PATTERN = re.compile(
    r"\b(log in|sign up|continue with google|continue with apple)\b",
    re.I,
)
LOGGER = logging.getLogger(__name__)
_CLOUDFLARE_COOKIE_NAMES = ("cf_clearance", "__cf_bm", "__cflb")
_UI_SETTLE_MS = 5_000


async def clear_chatgpt_challenge_cookies(context: BrowserContext) -> None:
    """Drop Cloudflare cookies while preserving the actual ChatGPT session cookies."""
    for cookie_name in _CLOUDFLARE_COOKIE_NAMES:
        await context.clear_cookies(name=cookie_name)


async def wait_for_challenge_to_clear(page: Page, retries: int = 20) -> bool:
    """Wait for a transient Cloudflare page to resolve on its own."""
    for _ in range(retries):
        title = await page.title()
        body_text = await page.locator("body").inner_text(timeout=5_000)
        if not looks_like_challenge_page(title, body_text, page.url):
            return True
        await page.wait_for_timeout(1_000)
    return False


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


async def wait_for_assistant_response(page: Page, previous_count: int) -> None:
    """Wait until a newly submitted assistant response is fully rendered."""
    await page.wait_for_function(
        """
        expectedCount => (
            document.querySelectorAll("[data-message-author-role='assistant']").length
            > expectedCount
        )
        """,
        arg=previous_count,
        timeout=180_000,
    )
    await page.wait_for_function(
        """
        () => {
            const turn = document.querySelector("section[data-turn='assistant']:last-of-type");
            if (!turn) return false;
            return !turn.querySelector("[aria-busy='true']");
        }
        """,
        timeout=600_000,
    )
    await page.wait_for_timeout(_UI_SETTLE_MS)


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


async def capture_audio_chunk(
    *,
    page: Page,
    downloads: list[Download],
    response_payloads: list[tuple[str, str, bytes]],
    diagnostics_dir: Path,
    chunk_index: int,
) -> list[Path]:
    """Capture one narrated audio chunk from the active assistant response."""
    downloads.clear()
    response_payloads.clear()
    chunk_dir = diagnostics_dir / f"chunk-{chunk_index:02d}"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    await page.wait_for_timeout(_UI_SETTLE_MS)
    assistant_turn = page.locator("section[data-turn='assistant']").last
    read_aloud_button = await locate_read_aloud_button(assistant_turn, page)
    if read_aloud_button is None:
        raise BrowserAutomationError("Could not find the ChatGPT read-aloud control.")
    LOGGER.info("chatgpt_audio_control_found")
    await read_aloud_button.click(timeout=10_000)
    LOGGER.info("chatgpt_audio_capture_wait_start")
    await _wait_for_audio_response_payload(page, response_payloads)
    LOGGER.info(
        "chatgpt_audio_capture_wait_done",
        extra={
            "context": {
                "downloads": len(downloads),
                "response_payloads": len(response_payloads),
            }
        },
    )
    network_paths = _write_network_payloads(chunk_dir, response_payloads)
    if network_paths:
        return network_paths
    raise BrowserAutomationError("Failed to capture the ChatGPT synthesize response.")


async def monitor_setup_challenge(page: Page, diagnostics_dir: Path) -> None:
    """Capture setup-browser diagnostics when ChatGPT stays on a challenge page."""
    wrote_snapshot = False
    while not page.is_closed():
        try:
            await page.wait_for_timeout(5_000)
            title = await page.title()
            body_text = await page.locator("body").inner_text(timeout=5_000)
            if not looks_like_challenge_page(title, body_text, page.url) or wrote_snapshot:
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
        except Exception as error:  # noqa: BLE001
            if page.is_closed() or _is_closed_page_error(error):
                return
            LOGGER.warning("setup_browser_monitor_failed", exc_info=error)


def _is_closed_page_error(error: Exception) -> bool:
    """Return whether the exception only indicates expected page shutdown."""
    return "Target page, context or browser has been closed" in str(error)
