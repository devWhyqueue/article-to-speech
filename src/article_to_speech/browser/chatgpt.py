from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import Download, Page, async_playwright

from article_to_speech.browser.capture import (
    artifact_dir,
    audio_hook_script,
    write_diagnostics,
)
from article_to_speech.browser.launch import (
    browser_stealth_script,
    hold_browser_profile,
    launch_chatgpt_context,
)
from article_to_speech.browser.support import (
    capture_audio_chunk,
    create_project,
    ensure_authenticated,
    final_artifact,
    get_or_create_page,
    monitor_setup_challenge,
    response_listener,
    submit_prompt,
)
from article_to_speech.browser.ui import (
    click_maybe_resilient,
    click_text,
    fill_editor,
    find_editor,
    open_new_chat,
    wait_for_editor,
)
from article_to_speech.core.config import Settings
from article_to_speech.core.exceptions import AuthenticationRequiredError, BrowserAutomationError
from article_to_speech.core.models import (
    AudioArtifact,
    BrowserStepLog,
    NarrationRequest,
    ResolvedArticle,
)
from article_to_speech.infra.audio import convert_to_mp3

LOGGER = logging.getLogger(__name__)


class ChatGPTBrowserAutomation:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def bootstrap_login(self) -> None:
        """Open the persistent ChatGPT browser profile for one-time manual login."""
        with hold_browser_profile(self._settings.browser_profile_dir):
            async with async_playwright() as playwright:
                context = await launch_chatgpt_context(playwright, self._settings)
                try:
                    page = await get_or_create_page(context)
                    await page.add_init_script(browser_stealth_script())
                    await page.goto(
                        "https://chatgpt.com/",
                        wait_until="domcontentloaded",
                        timeout=60_000,
                    )
                    LOGGER.info(
                        "setup_browser_ready",
                        extra={
                            "context": {
                                "novnc_url": "http://localhost:6080/vnc.html",
                                "profile_dir": str(self._settings.browser_profile_dir),
                            }
                        },
                    )
                    challenge_monitor = asyncio.create_task(
                        monitor_setup_challenge(
                            page,
                            artifact_dir(self._settings.diagnostics_dir, "setup-browser"),
                        )
                    )
                    try:
                        await asyncio.Event().wait()
                    finally:
                        challenge_monitor.cancel()
                        await asyncio.gather(challenge_monitor, return_exceptions=True)
                finally:
                    await context.close()

    async def synthesize_article(
        self,
        article: ResolvedArticle,
        requests: list[NarrationRequest],
    ) -> AudioArtifact:
        """Generate narrated article audio through the ChatGPT web UI."""
        diagnostics_dir = artifact_dir(
            self._settings.diagnostics_dir,
            article.title,
            article.final_url,
        )
        step_logs: list[BrowserStepLog] = []
        chunk_outputs: list[Path] = []

        with hold_browser_profile(self._settings.browser_profile_dir):
            async with async_playwright() as playwright:
                context = await launch_chatgpt_context(playwright, self._settings)
                page = await get_or_create_page(context)
                await page.add_init_script(audio_hook_script())
                await page.add_init_script(browser_stealth_script())
                downloads: list[Download] = []
                response_payloads: list[tuple[str, str, bytes]] = []
                capture_tasks: list[asyncio.Task[None]] = []
                context.on("response", response_listener(response_payloads, capture_tasks))
                page.on("download", lambda download: downloads.append(download))

                try:
                    await self._open_chatgpt(page, step_logs)
                    for request in requests:
                        await self._send_prompt(page, request, step_logs)
                        raw_paths = await capture_audio_chunk(
                            page=page,
                            downloads=downloads,
                            response_payloads=response_payloads,
                            diagnostics_dir=diagnostics_dir,
                            chunk_index=request.chunk_index,
                        )
                        for raw_path in raw_paths:
                            if raw_path.suffix.lower() == ".mp3":
                                chunk_outputs.append(raw_path)
                                continue
                            mp3_path = raw_path.with_suffix(".mp3")
                            convert_to_mp3(raw_path, mp3_path)
                            chunk_outputs.append(mp3_path)

                    for task in capture_tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*capture_tasks, return_exceptions=True)
                    return final_artifact(
                        article.title,
                        self._settings.artifacts_dir,
                        chunk_outputs,
                        article.final_url,
                    )
                except AuthenticationRequiredError:
                    await write_diagnostics(page, diagnostics_dir, step_logs)
                    raise
                except Exception as error:  # noqa: BLE001
                    await write_diagnostics(page, diagnostics_dir, step_logs)
                    raise BrowserAutomationError(str(error)) from error
                finally:
                    await context.close()

    async def _open_chatgpt(self, page: Page, step_logs: list[BrowserStepLog]) -> None:
        await self._record(step_logs, "open_home", "Navigating to ChatGPT")
        await page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60_000)
        await ensure_authenticated(page)
        await self._open_project(page, step_logs)
        await self._ensure_project_chat(page, step_logs)

    async def _open_project(self, page: Page, step_logs: list[BrowserStepLog]) -> None:
        await self._record(step_logs, "open_project", self._settings.chatgpt_project_name)
        if await self._goto_project_page(page):
            return
        await click_maybe_resilient(
            page,
            ["button[aria-label*='Sidebar']", "button[aria-label*='Open sidebar']"],
        )
        await page.wait_for_timeout(500)
        if await self._goto_project_page(page):
            return
        if await click_text(page, "Projects"):
            await page.wait_for_timeout(1_000)
            if await self._goto_project_page(page):
                return
        await create_project(page, self._settings.chatgpt_project_name)

    async def _ensure_project_chat(self, page: Page, step_logs: list[BrowserStepLog]) -> None:
        await self._record(step_logs, "ensure_chat", "Using project-local composer")
        if await find_editor(page) is not None:
            return
        if "/project" not in page.url:
            raise BrowserAutomationError(
                "ChatGPT did not remain inside the configured project page."
            )
        if not await open_new_chat(page):
            raise BrowserAutomationError("Could not open a new project chat in ChatGPT.")
        if await wait_for_editor(page):
            return
        raise BrowserAutomationError("Could not open a project chat composer in ChatGPT.")

    async def _send_prompt(
        self,
        page: Page,
        request: NarrationRequest,
        step_logs: list[BrowserStepLog],
    ) -> None:
        await self._record(
            step_logs,
            "send_prompt",
            f"Submitting chunk {request.chunk_index}/{request.chunk_count}",
        )
        assistant_messages = page.locator("[data-message-author-role='assistant']")
        previous_count = await assistant_messages.count()
        editor = await find_editor(page)
        if editor is None:
            raise BrowserAutomationError("Could not find the ChatGPT composer.")
        await fill_editor(editor, request.prompt_text)
        await submit_prompt(page)
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
        await page.wait_for_selector(
            "section[data-turn='assistant'] button[aria-label='More actions'], "
            "section[data-turn='assistant'] button[aria-label='Copy response']",
            timeout=60_000,
        )
        await page.wait_for_timeout(750)

    async def _record(self, step_logs: list[BrowserStepLog], step: str, detail: str) -> None:
        step_logs.append(BrowserStepLog(step=step, detail=detail))

    async def _goto_project_page(self, page: Page) -> bool:
        project_link = page.locator("a[data-sidebar-item='true']").filter(
            has_text=self._settings.chatgpt_project_name
        )
        if not await project_link.count():
            return False
        href = await project_link.first.get_attribute("href")
        if not href:
            return False
        await page.goto(urljoin(page.url, href), wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(1_000)
        return "/project" in page.url
