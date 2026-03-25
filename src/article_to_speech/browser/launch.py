from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NotRequired, TextIO, TypedDict, cast

from playwright.async_api import BrowserContext, Error, Playwright

from article_to_speech.core.config import Settings
from article_to_speech.core.exceptions import BrowserAutomationError
from article_to_speech.infra.archive_proxy import parse_proxy_settings

_LOCK_EX = fcntl.LOCK_EX  # pyright: ignore[reportAttributeAccessIssue]
_LOCK_NB = fcntl.LOCK_NB  # pyright: ignore[reportAttributeAccessIssue]
_LOCK_UN = fcntl.LOCK_UN  # pyright: ignore[reportAttributeAccessIssue]
_FLOCK = fcntl.flock  # pyright: ignore[reportAttributeAccessIssue]


class ViewportSize(TypedDict):
    width: int
    height: int


class BrowserContextOptions(TypedDict):
    headless: bool
    accept_downloads: bool
    args: list[str]
    ignore_default_args: list[str]
    locale: str
    user_agent: str
    proxy: NotRequired[dict[str, str | None]]
    timezone_id: NotRequired[str]
    viewport: ViewportSize


_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'language', { get: () => 'en-US' });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'vendor', { get: () => 'Google Inc.' });
const makePlugin = (name) => ({ name, filename: `${name}.so`, description: name });
const plugins = [makePlugin('PDF Viewer'), makePlugin('Chrome PDF Viewer'), makePlugin('Chromium PDF Viewer'), makePlugin('Microsoft Edge PDF Viewer'), makePlugin('WebKit built-in PDF')];
plugins.item = index => plugins[index] ?? null;
plugins.namedItem = name => plugins.find(plugin => plugin.name === name) ?? null;
Object.defineProperty(navigator, 'plugins', { get: () => plugins });
const mimeTypes = [{ type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' }];
mimeTypes.item = index => mimeTypes[index] ?? null;
mimeTypes.namedItem = name => mimeTypes.find(item => item.type === name) ?? null;
Object.defineProperty(navigator, 'mimeTypes', { get: () => mimeTypes });
window.chrome = window.chrome || { runtime: {}, app: {} };
const permissions = window.navigator.permissions;
const originalQuery = permissions?.query?.bind(permissions);
if (originalQuery) {
  permissions.query = parameters => (
    parameters?.name === 'notifications' ? Promise.resolve({ state: Notification.permission }) : originalQuery(parameters)
  );
}
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
            headless=options["headless"],
            accept_downloads=options["accept_downloads"],
            args=options["args"],
            ignore_default_args=options["ignore_default_args"],
            locale=options["locale"],
            user_agent=options["user_agent"],
            proxy=cast(Any, options.get("proxy")),
            timezone_id=options.get("timezone_id"),
            viewport=options["viewport"],
        )
    except Error as error:
        message = str(error)
        if "profile appears to be in use" in message.lower():
            raise BrowserAutomationError(
                "The persistent ChatGPT browser profile is locked. "
                "Stop any running setup-browser container and retry. "
                "If the prior run crashed, restart after the stale lock cleanup step."
            ) from error
        if _looks_like_missing_browser_dependency_error(message):
            raise BrowserAutomationError(
                "Local Chromium is missing required Linux libraries. "
                "Run `uv run playwright install --with-deps chromium` "
                "or `uv run playwright install-deps chromium`, then retry."
            ) from error
        raise


def build_browser_context_options(settings: Settings) -> BrowserContextOptions:
    """Build the Playwright persistent context options used for ChatGPT automation."""
    options: BrowserContextOptions = {
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


def browser_args() -> list[str]:
    """Return Chromium flags that keep the ChatGPT session stable inside Docker."""
    return [
        "--autoplay-policy=no-user-gesture-required",
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--disable-features=IsolateOrigins,site-per-process",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized",
    ]


def setup_browser_args(profile_dir: Path, start_url: str) -> list[str]:
    """Return Chromium flags for a manual setup-browser session."""
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


def browser_stealth_script() -> str:
    """Return an init script that reduces obvious automation fingerprints."""
    return _STEALTH_SCRIPT


def _is_missing_symlink_target(path: Path) -> bool:
    if not path.is_symlink():
        return False
    try:
        target = os.readlink(path)
    except OSError:
        return False
    return not Path(target).exists()


def _looks_like_missing_browser_dependency_error(message: str) -> bool:
    lowered = message.lower()
    return (
        "missing dependencies" in lowered
        or "error while loading shared libraries" in lowered
        or "host system is missing dependencies" in lowered
    )


def normalize_profile_shutdown_state(profile_dir: Path) -> None:
    """Mark Chromium profile state as clean to suppress crash-restore UI."""
    for relative_path in (Path("Default/Preferences"), Path("Local State")):
        candidate = profile_dir / relative_path
        _rewrite_shutdown_state(candidate)


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
