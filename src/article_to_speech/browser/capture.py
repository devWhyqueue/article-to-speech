from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import cast

from playwright.async_api import Error, Page, Response

from article_to_speech.core.models import BrowserStepLog


async def maybe_capture_response_bytes(
    response: Response,
    payloads: list[tuple[str, str, bytes]],
) -> None:
    """Capture response bytes for audio-like network responses."""
    content_type = response.headers.get("content-type", "")
    audio_like = content_type.startswith("audio/") or any(
        token in response.url.lower()
        for token in ("audio", "voice", "readaloud", ".mp3", ".m4a", ".wav")
    )
    if not audio_like:
        return
    try:
        payload = await response.body()
    except Error:
        return
    if payload:
        payloads.append((response.url, content_type, payload))


async def write_diagnostics(
    page: Page,
    diagnostics_dir: Path,
    step_logs: list[BrowserStepLog],
) -> None:
    """Persist screenshot, HTML, and step logs for a browser failure."""
    _ensure_directory(diagnostics_dir)
    _write_text_file(
        diagnostics_dir / "snapshot.json",
        json.dumps(await collect_browser_snapshot(page), indent=2, ensure_ascii=True),
    )
    await page.screenshot(path=str(diagnostics_dir / "failure.png"), full_page=True)
    html = await page.content()
    _write_text_file(diagnostics_dir / "failure.html", html)
    _write_text_file(
        diagnostics_dir / "steps.json",
        json.dumps([asdict(entry) for entry in step_logs], default=str, indent=2),
    )


async def collect_browser_snapshot(page: Page) -> dict[str, object]:
    """Collect the current page URL, title, and a small browser fingerprint snapshot."""
    snapshot = cast(
        dict[str, object],
        await page.evaluate(
            """
            () => ({
                navigator: {
                    userAgent: navigator.userAgent,
                    language: navigator.language,
                    languages: Array.from(navigator.languages),
                    platform: navigator.platform,
                    webdriver: navigator.webdriver,
                    hardwareConcurrency: navigator.hardwareConcurrency,
                    deviceMemory: navigator.deviceMemory ?? null,
                    plugins: navigator.plugins.length,
                },
                window: {
                    innerWidth: window.innerWidth,
                    innerHeight: window.innerHeight,
                    outerWidth: window.outerWidth,
                    outerHeight: window.outerHeight,
                    devicePixelRatio: window.devicePixelRatio,
                },
                screen: {
                    width: window.screen.width,
                    height: window.screen.height,
                    colorDepth: window.screen.colorDepth,
                },
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone ?? null,
            })
            """
        ),
    )
    snapshot["title"] = await page.title()
    snapshot["url"] = page.url
    return snapshot


def extension_from_audio(url: str, content_type: str) -> str:
    """Guess an audio file extension from a URL and content type."""
    lowered = f"{url} {content_type}".lower()
    if "mpeg" in lowered or ".mp3" in lowered:
        return ".mp3"
    if "mp4" in lowered or "m4a" in lowered:
        return ".m4a"
    if "wav" in lowered:
        return ".wav"
    return ".webm"


def audio_hook_script() -> str:
    """Return the browser bootstrap script that tracks played audio sources."""
    return """
    (() => {
      window.__atsAudioState = { sources: [] };
      const originalPlay = HTMLMediaElement.prototype.play;
      HTMLMediaElement.prototype.play = function(...args) {
        try {
          window.__atsAudioState.sources.push({
            src: this.currentSrc || this.src || "",
            timestamp: Date.now(),
          });
        } catch (error) {
          console.warn("audio hook failed", error);
        }
        return originalPlay.apply(this, args);
      };
    })();
    """


def artifact_dir(root: Path, title: str, source_url: str | None = None) -> Path:
    """Return a stable artifact subdirectory for the given article title."""
    slug = _artifact_slug(title, source_url)
    directory = root / slug
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def artifact_file_name(title: str, source_url: str | None, extension: str) -> str:
    """Return a descriptive artifact file name for the given article."""
    normalized_extension = extension if extension.startswith(".") else f".{extension}"
    return f"{_artifact_slug(title, source_url)}{normalized_extension}"


def _artifact_slug(title: str, source_url: str | None) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower() or "article"
    snapshot_id = _archive_snapshot_id(source_url)
    if snapshot_id:
        slug = f"{slug}-{snapshot_id}"
    return slug


def _archive_snapshot_id(source_url: str | None) -> str | None:
    if not source_url:
        return None
    match = re.search(r"archive\.(?:is|ph|today)/([A-Za-z0-9]+)", source_url)
    if match is None:
        return None
    return match.group(1).lower()


def _ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write_text_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
