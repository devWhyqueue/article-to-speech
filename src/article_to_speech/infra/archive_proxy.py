from __future__ import annotations

import logging
from pathlib import Path
from typing import NotRequired, TypedDict
from urllib.parse import urlsplit

import httpx

ARCHIVE_BASE_URL = "https://archive.is/"
ARCHIVE_PROXY_TEST_TIMEOUT_SECONDS = 10.0
LOGGER = logging.getLogger(__name__)


class ProxySettings(TypedDict):
    server: str
    username: NotRequired[str]
    password: NotRequired[str]


def archive_launch_proxies(proxy_urls: tuple[str, ...]) -> tuple[ProxySettings | None, ...]:
    """Return configured archive proxies in order, plus a final direct attempt."""
    proxies = tuple(parse_proxy_settings(url) for url in proxy_urls)
    return (*proxies, None)


def parse_proxy_settings(proxy_url: str) -> ProxySettings:
    """Parse a proxy URL into Playwright launch proxy settings."""
    parsed = urlsplit(proxy_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.port is None:
        raise ValueError(f"Invalid proxy URL: {proxy_url}")
    proxy: ProxySettings = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        proxy["username"] = parsed.username
    if parsed.password:
        proxy["password"] = parsed.password
    return proxy


async def resolve_archive_proxy_urls(
    *,
    configured_urls: tuple[str, ...],
    proxy_list_url: str | None,
    user_agent: str,
    cache_path: Path | None = None,
) -> tuple[str, ...]:
    """Return reachable archive proxies from static config and an optional remote list."""
    cached_urls = load_cached_archive_proxy_urls(cache_path)
    if cached_urls:
        return cached_urls
    if configured_urls:
        working_urls = await filter_reachable_archive_proxy_urls(
            dedupe_proxy_urls(configured_urls),
            user_agent=user_agent,
        )
        if working_urls:
            write_cached_archive_proxy_urls(cache_path, working_urls)
            return working_urls
    if proxy_list_url is None:
        write_cached_archive_proxy_urls(cache_path, ())
        return ()
    downloaded_urls = await download_archive_proxy_urls(proxy_list_url)
    refreshed_candidates = dedupe_proxy_urls((*configured_urls, *downloaded_urls))
    if not refreshed_candidates:
        write_cached_archive_proxy_urls(cache_path, ())
        return ()
    working_urls = await filter_reachable_archive_proxy_urls(
        refreshed_candidates,
        user_agent=user_agent,
    )
    write_cached_archive_proxy_urls(cache_path, working_urls)
    return working_urls


async def download_archive_proxy_urls(proxy_list_url: str) -> tuple[str, ...]:
    """Download a proxy list and normalize it into proxy URLs."""
    async with httpx.AsyncClient(timeout=ARCHIVE_PROXY_TEST_TIMEOUT_SECONDS) as client:
        response = await client.get(proxy_list_url)
        response.raise_for_status()
    return parse_proxy_list(response.text)


def parse_proxy_list(raw_text: str) -> tuple[str, ...]:
    """Parse a downloaded proxy list into normalized proxy URLs."""
    proxy_urls: list[str] = []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "://" in line:
            proxy_urls.append(line)
            continue
        parts = line.split(":")
        if len(parts) != 4:
            continue
        host, port, username, password = parts
        if not host or not port or not username or not password:
            continue
        proxy_urls.append(f"http://{username}:{password}@{host}:{port}")
    return tuple(proxy_urls)


def dedupe_proxy_urls(proxy_urls: tuple[str, ...]) -> tuple[str, ...]:
    """Deduplicate proxy URLs while preserving order."""
    seen: set[str] = set()
    unique_urls: list[str] = []
    for proxy_url in proxy_urls:
        if proxy_url in seen:
            continue
        seen.add(proxy_url)
        unique_urls.append(proxy_url)
    return tuple(unique_urls)


async def filter_reachable_archive_proxy_urls(
    proxy_urls: tuple[str, ...],
    *,
    user_agent: str,
) -> tuple[str, ...]:
    """Keep only proxies that can reach archive.is."""
    working_urls: list[str] = []
    for proxy_url in proxy_urls:
        if await archive_proxy_reaches_archive(proxy_url, user_agent=user_agent):
            working_urls.append(proxy_url)
    return tuple(working_urls)


async def archive_proxy_reaches_archive(proxy_url: str, *, user_agent: str) -> bool:
    """Return whether the given proxy can reach archive.is without proxy-side rejection."""
    try:
        async with httpx.AsyncClient(
            proxy=proxy_url,
            timeout=ARCHIVE_PROXY_TEST_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        ) as client:
            response = await client.get(ARCHIVE_BASE_URL)
    except httpx.HTTPError as error:
        LOGGER.warning(
            "archive_proxy_probe_failed",
            extra={"context": {"proxy_url": redact_proxy_url(proxy_url), "error": str(error)}},
        )
        return False
    if response.headers.get("X-Webshare-Reason") is not None:
        return False
    return response.status_code < 400 and response.status_code != 429


def redact_proxy_url(proxy_url: str) -> str:
    """Return a proxy URL without embedded credentials."""
    parsed = urlsplit(proxy_url)
    if not parsed.hostname or parsed.port is None:
        return proxy_url
    return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"


def load_cached_archive_proxy_urls(cache_path: Path | None) -> tuple[str, ...]:
    """Load cached archive proxy URLs from disk."""
    if cache_path is None or not cache_path.exists():
        return ()
    return dedupe_proxy_urls(
        tuple(
            line.strip()
            for line in cache_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    )


def write_cached_archive_proxy_urls(
    cache_path: Path | None,
    proxy_urls: tuple[str, ...],
) -> None:
    """Persist the current set of working archive proxy URLs."""
    if cache_path is None:
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("\n".join(proxy_urls), encoding="utf-8")
