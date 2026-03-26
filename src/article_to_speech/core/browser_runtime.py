from __future__ import annotations

import asyncio
import json
import os
import socket
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Error, Page, Playwright

from article_to_speech.core.exceptions import (
    AuthenticationRequiredError,
    BrowserAutomationError,
)

_WORKSPACE_MARKERS = ("Chat history", "Projects", "Your chats", "\nMe\n")
_PROJECT_MARKER = "Articles"


def browser_args() -> list[str]:
    """Return Chromium flags for the managed browser runtime."""
    return [
        "--autoplay-policy=no-user-gesture-required",
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--disable-features=IsolateOrigins,site-per-process",
        "--disable-gpu",
        "--disable-session-crashed-bubble",
        "--disable-setuid-sandbox",
        "--disable-software-rasterizer",
        "--hide-crash-restore-bubble",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-sandbox",
        "--start-maximized",
    ]


def setup_browser_args(profile_dir: Path, start_url: str) -> list[str]:
    """Return Chromium flags for manual setup-browser launch."""
    return [
        f"--user-data-dir={profile_dir}",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-setuid-sandbox",
        "--disable-session-crashed-bubble",
        "--disable-software-rasterizer",
        "--hide-crash-restore-bubble",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        "--no-sandbox",
        "--start-maximized",
        start_url,
    ]


def automation_browser_args(profile_dir: Path) -> list[str]:
    """Return Chromium flags for automation without a forced start URL."""
    return [
        f"--user-data-dir={profile_dir}",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-setuid-sandbox",
        "--disable-session-crashed-bubble",
        "--disable-software-rasterizer",
        "--hide-crash-restore-bubble",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-sandbox",
        "--start-maximized",
    ]


def browser_process_env() -> dict[str, str]:
    """Return the managed Chromium environment overrides."""
    env = dict(os.environ)
    env.pop("DBUS_SESSION_BUS_ADDRESS", None)
    env.setdefault("NO_AT_BRIDGE", "1")
    return env


async def connect_chromium_over_cdp(playwright: Playwright, debug_port: int) -> Any:
    for _ in range(60):
        try:
            return await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port}")
        except Error:
            await asyncio.sleep(0.5)
    raise BrowserAutomationError("Timed out waiting for the setup-browser Chromium instance.")


def free_local_port() -> int:
    """Return a free local port for temporary CDP attach."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def get_or_create_page(context: BrowserContext) -> Page:
    best_page: Page | None = None
    best_score = -1
    for _ in range(10):
        for page in context.pages:
            score = await workspace_page_score(page)
            if score > best_score:
                best_page = page
                best_score = score
        if best_page is not None and await is_reusable_workspace_page(best_page):
            await close_degraded_chatgpt_tabs(context, keeper=best_page, keeper_score=best_score)
            await best_page.bring_to_front()
            return best_page
        if context.pages:
            await context.pages[0].wait_for_timeout(1_000)
    if best_page is not None and await is_reusable_workspace_page(best_page):
        await close_degraded_chatgpt_tabs(context, keeper=best_page, keeper_score=best_score)
        await best_page.bring_to_front()
        return best_page
    for page in context.pages:
        if "chatgpt.com" in page.url and not page.is_closed():
            await page.bring_to_front()
            return page
    return context.pages[0] if context.pages else await context.new_page()


def is_project_page_url(url: str) -> bool:
    """Return whether the ChatGPT URL points into a project workspace."""
    return "/project" in url or "/g/g-p-" in url


async def wait_for_workspace_shell(page: Page, retries: int = 20) -> bool:
    for _ in range(retries):
        body_text = await page_text(page, timeout=10_000)
        if any(marker in body_text for marker in _WORKSPACE_MARKERS):
            return True
        await page.wait_for_timeout(1_000)
    return False


async def wait_for_project_workspace_ready(
    page: Page,
    project_name: str,
    *,
    retries: int = 20,
) -> bool:
    project_name_lower = project_name.lower()
    for _ in range(retries):
        if not is_project_page_url(page.url):
            await page.wait_for_timeout(1_000)
            continue
        body_text = (await page_text(page, timeout=10_000)).lower()
        if any(marker.lower() in body_text for marker in _WORKSPACE_MARKERS) and (
            project_name_lower in body_text or page.url.lower().count(project_name_lower) > 0
        ):
            return True
        await page.wait_for_timeout(1_000)
    return False


async def workspace_page_score(page: Page) -> int:
    if page.is_closed() or "chatgpt.com" not in page.url:
        return -1
    body_text = await page_text(page)
    markers = (*_WORKSPACE_MARKERS, _PROJECT_MARKER)
    score = sum(1 for marker in markers if marker in body_text)
    if is_project_page_url(page.url):
        score += 3
    return score


async def is_reusable_workspace_page(page: Page) -> bool:
    if page.is_closed() or "chatgpt.com" not in page.url:
        return False
    body_text = await page_text(page)
    return any(marker in body_text for marker in _WORKSPACE_MARKERS)


async def ensure_reusable_workspace_page(
    page: Page,
    *,
    clear_cookies: Callable[[BrowserContext], Awaitable[None]],
    ensure_authenticated: Callable[[Page], Awaitable[None]],
) -> Page:
    for attempt in range(2):
        if "chatgpt.com" not in page.url:
            await page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60_000)
        else:
            await page.bring_to_front()
        try:
            await ensure_authenticated(page)
        except AuthenticationRequiredError:
            if attempt != 0:
                raise
            await clear_cookies(page.context)
            await page.wait_for_timeout(2_000)
            continue
        await wait_for_workspace_shell(page, retries=20)
        if await is_reusable_workspace_page(page):
            return page
    raise BrowserAutomationError("Could not open a healthy authenticated ChatGPT workspace tab.")


async def close_degraded_chatgpt_tabs(
    context: BrowserContext,
    *,
    keeper: Page,
    keeper_score: int,
) -> None:
    """Close duplicate ChatGPT tabs that are clearly worse than the selected keeper."""
    for page in list(context.pages):
        if page == keeper or page.is_closed() or "chatgpt.com" not in page.url:
            continue
        score = await workspace_page_score(page)
        should_close = score >= 0 and (score <= 1 if keeper_score >= 4 else score == 0)
        if should_close:
            try:
                await page.close()
            except Error:
                continue


async def page_text(page: Page, timeout: int = 3_000) -> str:
    """Return page body text, tolerating transient closed/unstable-page errors."""
    try:
        return await page.locator("body").inner_text(timeout=timeout)
    except Error:
        return ""


def looks_like_missing_browser_dependency_error(message: str) -> bool:
    """Return whether Chromium failed to start due to missing host libraries."""
    lowered = message.lower()
    return (
        "missing dependencies" in lowered
        or "error while loading shared libraries" in lowered
        or "host system is missing dependencies" in lowered
    )


def normalize_profile_shutdown_state(profile_dir: Path) -> None:
    """Mark Chromium profile state as clean to suppress crash-restore UI."""
    for relative_path in (Path("Default/Preferences"), Path("Local State")):
        _rewrite_shutdown_state(profile_dir / relative_path)


def _rewrite_shutdown_state(path: Path) -> None:
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    payload["exit_type"] = "Normal"
    payload["exited_cleanly"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
