from __future__ import annotations

import asyncio
import fcntl
import json
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, TextIO, cast

from playwright.async_api import BrowserContext, Error, Playwright

from article_to_speech.core.browser_runtime import (
    automation_browser_args,
    browser_args,
    browser_process_env,
    connect_chromium_over_cdp,
    free_local_port,
    looks_like_missing_browser_dependency_error,
    normalize_profile_shutdown_state,
)
from article_to_speech.core.config import Settings
from article_to_speech.core.exceptions import BrowserAutomationError
from article_to_speech.infra.archive_proxy import parse_proxy_settings

_browser_process_env = browser_process_env
_looks_like_missing_browser_dependency_error = looks_like_missing_browser_dependency_error
_LOCK_EX = fcntl.LOCK_EX  # pyright: ignore[reportAttributeAccessIssue]
_LOCK_NB = fcntl.LOCK_NB  # pyright: ignore[reportAttributeAccessIssue]
_LOCK_UN = fcntl.LOCK_UN  # pyright: ignore[reportAttributeAccessIssue]
_FLOCK = fcntl.flock  # pyright: ignore[reportAttributeAccessIssue]
_SHARED_BROWSER_STATE_FILE = ".setup-browser.json"
_STEALTH_SCRIPT = """
Object.defineProperty(navigator,'webdriver',{get:()=>undefined}); Object.defineProperty(navigator,'language',{get:()=>'en-US'}); Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']}); Object.defineProperty(navigator,'vendor',{get:()=>'Google Inc.'});
const makePlugin=name=>({name,filename:`${name}.so`,description:name}); const plugins=[makePlugin('PDF Viewer'),makePlugin('Chrome PDF Viewer'),makePlugin('Chromium PDF Viewer'),makePlugin('Microsoft Edge PDF Viewer'),makePlugin('WebKit built-in PDF')]; plugins.item=index=>plugins[index]??null; plugins.namedItem=name=>plugins.find(plugin=>plugin.name===name)??null; Object.defineProperty(navigator,'plugins',{get:()=>plugins});
const mimeTypes=[{type:'application/pdf',suffixes:'pdf',description:'Portable Document Format'}]; mimeTypes.item=index=>mimeTypes[index]??null; mimeTypes.namedItem=name=>mimeTypes.find(item=>item.type===name)??null; Object.defineProperty(navigator,'mimeTypes',{get:()=>mimeTypes});
window.chrome=window.chrome||{runtime:{},app:{}}; const permissions=window.navigator.permissions; const originalQuery=permissions?.query?.bind(permissions);
if (originalQuery) { permissions.query = parameters => (parameters?.name === 'notifications' ? Promise.resolve({ state: Notification.permission }) : originalQuery(parameters)); }
"""


class BrowserProfileLease:
    """Coordinate exclusive access to the shared persistent browser profile."""

    def __init__(self, profile_dir: Path) -> None:
        self._profile_dir = profile_dir
        self._lock_file = profile_dir / ".automation.lock"
        self._handle: TextIO | None = None

    def acquire(self) -> None:
        """Acquire exclusive profile access for the current process."""
        self._lock_file.parent.mkdir(parents=True, exist_ok=True)
        handle = self._lock_file.open("a+", encoding="utf-8")
        try:
            _FLOCK(handle.fileno(), _LOCK_EX | _LOCK_NB)
        except BlockingIOError as error:
            handle.close()
            raise BrowserAutomationError(
                "The persistent ChatGPT browser profile is already in use. "
                "Stop any running setup-browser or bot container before retrying."
            ) from error
        self._handle = handle

    def release(self) -> None:
        """Release the current profile lease."""
        if self._handle is None:
            return
        _FLOCK(self._handle.fileno(), _LOCK_UN)
        self._handle.close()
        self._handle = None

    def clear_stale_chromium_locks(self) -> list[str]:
        """Remove stale Chromium singleton files left behind by prior runs."""
        socket_link = self._profile_dir / "SingletonSocket"
        if not _is_missing_symlink_target(socket_link):
            return []
        removed: list[str] = []
        for name in ("SingletonCookie", "SingletonLock", "SingletonSocket"):
            candidate = self._profile_dir / name
            if candidate.exists() or candidate.is_symlink():
                candidate.unlink()
                removed.append(name)
        return removed


@contextmanager
def hold_browser_profile(profile_dir: Path) -> Iterator[BrowserProfileLease]:
    """Hold the persistent browser profile lease for the duration of a launch."""
    lease = BrowserProfileLease(profile_dir)
    lease.acquire()
    try:
        lease.clear_stale_chromium_locks()
        normalize_profile_shutdown_state(profile_dir)
        yield lease
    finally:
        lease.release()


async def launch_chatgpt_context(playwright: Playwright, settings: Settings) -> BrowserContext:
    """Launch the persistent ChatGPT browser context with a human-like profile."""
    options = build_browser_context_options(settings)
    try:
        return await playwright.chromium.launch_persistent_context(
            str(settings.browser_profile_dir),
            executable_path=playwright.chromium.executable_path,
            headless=options["headless"],
            accept_downloads=options["accept_downloads"],
            args=options["args"],
            ignore_default_args=options["ignore_default_args"],
            locale=options["locale"],
            user_agent=options["user_agent"],
            proxy=cast(Any, options.get("proxy")),
            timezone_id=options.get("timezone_id"),
            viewport=options["viewport"],
            env=cast(dict[str, str | float | bool], browser_process_env()),
        )
    except Error as error:
        message = str(error)
        if "profile appears to be in use" in message.lower():
            raise BrowserAutomationError(
                "The persistent ChatGPT browser profile is locked. "
                "Stop any running setup-browser container and retry. "
                "If the prior run crashed, restart after the stale lock cleanup step."
            ) from error
        if looks_like_missing_browser_dependency_error(message):
            raise BrowserAutomationError(
                "Local Chromium is missing required Linux libraries. "
                "Run `uv run playwright install --with-deps chromium` "
                "or `uv run playwright install-deps chromium`, then retry."
            ) from error
        raise


@asynccontextmanager
async def open_chatgpt_context(
    playwright: Playwright, settings: Settings
) -> AsyncIterator[BrowserContext]:
    """Open the ChatGPT browser context using the closest possible runtime to setup-browser."""
    if settings.chatgpt_browser_headless:
        context = await launch_chatgpt_context(playwright, settings)
        try:
            yield context
        finally:
            await context.close()
        return
    attached_context = await _shared_browser_context(playwright, settings.browser_profile_dir)
    if attached_context is not None:
        yield attached_context
        return
    with hold_browser_profile(settings.browser_profile_dir):
        debug_port = free_local_port()
        command = [
            os.fspath(playwright.chromium.executable_path),
            *automation_browser_args(settings.browser_profile_dir),
            f"--remote-debugging-port={debug_port}",
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            env=browser_process_env(),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        browser = None
        try:
            browser = await connect_chromium_over_cdp(playwright, debug_port)
            if not browser.contexts:
                raise BrowserAutomationError(
                    "Chromium started without an accessible persistent context."
                )
            yield browser.contexts[0]
        finally:
            if browser is not None:
                await browser.close()
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=10)
                except TimeoutError:
                    process.kill()
                    await process.wait()


def build_browser_context_options(settings: Settings) -> dict[str, Any]:
    """Build the Playwright persistent context options used for ChatGPT automation."""
    options: dict[str, Any] = {
        "headless": settings.chatgpt_browser_headless,
        "accept_downloads": True,
        "args": browser_args(),
        "ignore_default_args": ["--enable-automation"],
        "locale": settings.browser_locale,
        "user_agent": settings.http_user_agent,
        "viewport": {"width": 1440, "height": 960},
    }
    if settings.chatgpt_proxy_url is not None:
        options["proxy"] = cast(
            dict[str, str | None], dict(parse_proxy_settings(settings.chatgpt_proxy_url))
        )
    if settings.browser_timezone is not None:
        options["timezone_id"] = settings.browser_timezone
    return options


def browser_stealth_script() -> str:
    """Return an init script that reduces obvious automation fingerprints."""
    return _STEALTH_SCRIPT


def write_shared_browser_debug_port(profile_dir: Path, debug_port: int) -> None:
    """Record the setup-browser CDP port for later automation attachment."""
    _shared_browser_state_path(profile_dir).write_text(
        json.dumps({"debug_port": debug_port}), encoding="utf-8"
    )


def clear_shared_browser_debug_port(profile_dir: Path) -> None:
    """Remove the setup-browser CDP metadata file."""
    _shared_browser_state_path(profile_dir).unlink(missing_ok=True)


def _is_missing_symlink_target(path: Path) -> bool:
    if not path.is_symlink():
        return False
    try:
        target = os.readlink(path)
    except OSError:
        return False
    return not Path(target).exists()


async def _shared_browser_context(
    playwright: Playwright, profile_dir: Path
) -> BrowserContext | None:
    debug_port = _read_shared_browser_debug_port(profile_dir)
    if debug_port is None:
        return None
    try:
        browser = await connect_chromium_over_cdp(playwright, debug_port)
    except BrowserAutomationError:
        clear_shared_browser_debug_port(profile_dir)
        return None
    if not browser.contexts:
        clear_shared_browser_debug_port(profile_dir)
        return None
    return browser.contexts[0]


def _read_shared_browser_debug_port(profile_dir: Path) -> int | None:
    try:
        payload = json.loads(_shared_browser_state_path(profile_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _find_running_browser_debug_port(profile_dir)
    debug_port = payload.get("debug_port")
    if isinstance(debug_port, int):
        return debug_port
    return _find_running_browser_debug_port(profile_dir)


def _shared_browser_state_path(profile_dir: Path) -> Path:
    return profile_dir / _SHARED_BROWSER_STATE_FILE


def _find_running_browser_debug_port(profile_dir: Path) -> int | None:
    profile_arg = f"--user-data-dir={profile_dir}"
    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue
        try:
            raw_cmdline = (proc_dir / "cmdline").read_bytes()
        except OSError:
            continue
        if not raw_cmdline:
            continue
        args = [part.decode("utf-8", errors="ignore") for part in raw_cmdline.split(b"\0") if part]
        if profile_arg not in args:
            continue
        for arg in args:
            if arg.startswith("--remote-debugging-port="):
                suffix = arg.removeprefix("--remote-debugging-port=")
                if suffix.isdigit():
                    return int(suffix)
    return None
