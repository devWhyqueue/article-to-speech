from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from playwright.async_api import Download, Page, async_playwright

from article_to_speech.browser.capture import (
    artifact_dir,
    audio_hook_script,
    response_listener,
    write_diagnostics,
)
from article_to_speech.browser.launch import (
    browser_stealth_script,
    hold_browser_profile,
    open_chatgpt_context,
)
from article_to_speech.browser.support import (
    capture_audio_chunk,
    clear_chatgpt_challenge_cookies,
    ensure_authenticated,
    final_artifact,
    wait_for_assistant_response,
    wait_for_challenge_to_clear,
)
from article_to_speech.browser.ui import (
    click_maybe_resilient,
    fill_editor,
    find_editor,
    goto_project_page,
    has_project_chat_controls,
    open_new_chat,
    open_workspace_root,
    submit_prompt,
    wait_for_editor,
)
from article_to_speech.core.browser_runtime import (
    ensure_reusable_workspace_page,
    get_or_create_page,
    is_project_page_url,
    wait_for_project_workspace_ready,
)
from article_to_speech.core.config import Settings
from article_to_speech.core.exceptions import AuthenticationRequiredError, BrowserAutomationError
from article_to_speech.core.models import (
    AudioArtifact,
    BrowserStepLog,
    NarrationRequest,
    ResolvedArticle,
)
from article_to_speech.infra.audio import convert_to_mp3, run_manual_setup_browser

LOGGER = logging.getLogger(__name__)


class ChatGPTBrowserAutomation:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def bootstrap_login(self) -> None:
        with hold_browser_profile(self._settings.browser_profile_dir):
            async with async_playwright() as playwright:
                executable_path = Path(playwright.chromium.executable_path)
            await run_manual_setup_browser(executable_path, self._settings.browser_profile_dir)

    async def synthesize_article(
        self,
        article: ResolvedArticle,
        requests: list[NarrationRequest],
    ) -> AudioArtifact:
        diagnostics_dir = artifact_dir(
            self._settings.diagnostics_dir, article.title, article.final_url
        )
        step_logs: list[BrowserStepLog] = []
        chunk_outputs: list[Path] = []
        async with async_playwright() as playwright:
            async with open_chatgpt_context(playwright, self._settings) as context:
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
                    for request_index, request in enumerate(requests, start=1):
                        await self._send_prompt(page, request, step_logs)
                        raw_paths = await capture_audio_chunk(
                            page=page,
                            downloads=downloads,
                            response_payloads=response_payloads,
                            diagnostics_dir=diagnostics_dir,
                            chunk_index=request_index,
                        )
                        for raw_path in raw_paths:
                            if raw_path.suffix.lower() == ".mp3":
                                chunk_outputs.append(raw_path)
                                continue
                            mp3_path = raw_path.with_suffix(".mp3")
                            convert_to_mp3(raw_path, mp3_path)
                            chunk_outputs.append(mp3_path)
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
                    for task in capture_tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*capture_tasks, return_exceptions=True)

    async def _open_chatgpt(self, page: Page, step_logs: list[BrowserStepLog]) -> None:
        step_logs.append(BrowserStepLog(step="open_home", detail="Navigating to ChatGPT"))
        page = await ensure_reusable_workspace_page(
            page,
            clear_cookies=clear_chatgpt_challenge_cookies,
            ensure_authenticated=ensure_authenticated,
        )
        await self._open_project(page, step_logs)
        await self._ensure_project_chat(page, step_logs)

    async def _open_project(self, page: Page, step_logs: list[BrowserStepLog]) -> None:
        step_logs.append(
            BrowserStepLog(step="open_project", detail=self._settings.chatgpt_project_name)
        )
        await page.bring_to_front()
        await page.wait_for_load_state("domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(5_000)
        await open_workspace_root(page)
        await page.wait_for_timeout(3_000)
        for attempt in range(2):
            if await goto_project_page(page, self._settings.chatgpt_project_name):
                if await self._wait_for_project_ready(page):
                    return
            if attempt == 0:
                await click_maybe_resilient(
                    page,
                    ["button[aria-label*='Sidebar']", "button[aria-label*='Open sidebar']"],
                )
                await page.wait_for_timeout(2_000)
        raise BrowserAutomationError(
            f"Could not find the existing ChatGPT project '{self._settings.chatgpt_project_name}' "
            "from the authenticated workspace tab."
        )

    async def _ensure_project_chat(self, page: Page, step_logs: list[BrowserStepLog]) -> None:
        step_logs.append(BrowserStepLog(step="ensure_chat", detail="Using project-local composer"))
        if not is_project_page_url(page.url):
            raise BrowserAutomationError(
                "ChatGPT did not remain inside the configured project page."
            )
        if not await wait_for_challenge_to_clear(page):
            await clear_chatgpt_challenge_cookies(page.context)
            await page.goto(page.url, wait_until="domcontentloaded", timeout=60_000)
            if not await wait_for_challenge_to_clear(page):
                raise BrowserAutomationError("ChatGPT project page stayed on a Cloudflare check.")
        if not await self._wait_for_project_ready(page):
            raise BrowserAutomationError(
                "ChatGPT project page did not finish loading into a stable authenticated state."
            )
        await page.wait_for_timeout(3_000)
        if await wait_for_editor(page, retries=8):
            return
        if not await open_new_chat(page):
            raise BrowserAutomationError("Could not open a new project chat in ChatGPT.")
        if await self._wait_for_project_ready(page) and await wait_for_editor(page, retries=15):
            return
        raise BrowserAutomationError("Could not open a project chat composer in ChatGPT.")

    async def _send_prompt(
        self,
        page: Page,
        request: NarrationRequest,
        step_logs: list[BrowserStepLog],
    ) -> None:
        step_logs.append(
            BrowserStepLog(
                step="send_prompt",
                detail="Submitting narration prompt",
            )
        )
        assistant_messages = page.locator("[data-message-author-role='assistant']")
        previous_count = await assistant_messages.count()
        editor = await find_editor(page)
        if editor is None:
            raise BrowserAutomationError("Could not find the ChatGPT composer.")
        await fill_editor(editor, request.prompt_text)
        await submit_prompt(page)
        await wait_for_assistant_response(page, previous_count)

    async def _wait_for_project_ready(self, page: Page) -> bool:
        for _ in range(20):
            if is_project_page_url(page.url) and await has_project_chat_controls(page):
                return True
            if await wait_for_project_workspace_ready(
                page, self._settings.chatgpt_project_name, retries=1
            ):
                return True
            await page.wait_for_timeout(1_000)
        return False
