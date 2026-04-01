from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse, urlsplit, urlunsplit

from playwright.async_api import Browser, BrowserContext, Page, TimeoutError, async_playwright

from article_to_speech.core.browser_runtime import browser_args
from article_to_speech.core.config import Settings
from article_to_speech.infra.archive_proxy import (
    ProxySettings,
    parse_proxy_settings,
    resolve_archive_proxy_urls,
    write_cached_archive_proxy_urls,
)

ARCHIVE_BASE_URL = "https://archive.is/"


@dataclass(slots=True, frozen=True)
class RenderedPage:
    html: str
    final_url: str


class BrowserPageFetcher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._archive_proxy_urls_cache: tuple[str, ...] | None = None
        self._archive_proxy_cache_path = self._settings.state_db_path.parent / "archive-proxies.txt"

    async def render_html(self, url: str) -> RenderedPage:
        """Render a page in Chromium and return the final DOM HTML."""
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=self._settings.browser_headless,
                args=browser_args(),
            )
            try:
                context = await self._new_context(browser)
                try:
                    page = await context.new_page()
                    await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                    await self._settle_page(page)
                    return RenderedPage(html=await page.content(), final_url=page.url)
                finally:
                    await context.close()
            finally:
                await browser.close()

    async def render_archive_html(self, url: str) -> RenderedPage:
        """Render an archive.is snapshot page for the given article URL."""
        async with async_playwright() as playwright:
            last_error: Exception | None = None
            for archive_url in archive_lookup_urls(url):
                for proxy_url in (*await self._archive_proxy_urls(), None):
                    proxy = parse_proxy_settings(proxy_url) if proxy_url is not None else None
                    try:
                        return await self._render_archive_with_proxy(playwright, archive_url, proxy)
                    except Exception as error:  # noqa: BLE001
                        if proxy_url is not None:
                            self._drop_archive_proxy_url(proxy_url)
                        last_error = error
            if last_error is None:
                raise TimeoutError("Archive render failed")
            raise last_error

    async def _archive_proxy_urls(self) -> tuple[str, ...]:
        if self._archive_proxy_urls_cache is not None:
            return self._archive_proxy_urls_cache
        proxy_urls = await resolve_archive_proxy_urls(
            configured_urls=self._settings.archive_proxy_urls,
            proxy_list_url=self._settings.archive_proxy_list_url,
            user_agent=self._settings.http_user_agent,
            cache_path=self._archive_proxy_cache_path,
        )
        self._archive_proxy_urls_cache = proxy_urls
        return proxy_urls

    def _drop_archive_proxy_url(self, proxy_url: str) -> None:
        cached_proxy_urls = self._archive_proxy_urls_cache
        if cached_proxy_urls is None or proxy_url not in cached_proxy_urls:
            return
        self._archive_proxy_urls_cache = tuple(
            candidate_proxy_url
            for candidate_proxy_url in cached_proxy_urls
            if candidate_proxy_url != proxy_url
        )
        write_cached_archive_proxy_urls(
            self._archive_proxy_cache_path,
            self._archive_proxy_urls_cache,
        )

    async def _render_archive_with_proxy(
        self,
        playwright,
        archive_url: str,
        proxy: ProxySettings | None,
    ) -> RenderedPage:
        launch_kwargs: dict[str, object] = {
            "headless": self._settings.browser_headless,
            "args": browser_args(),
        }
        if proxy is not None:
            launch_kwargs["proxy"] = proxy
        browser = await playwright.chromium.launch(**launch_kwargs)
        try:
            context = await self._new_context(browser)
            try:
                page = await context.new_page()
                await page.goto(archive_url, wait_until="domcontentloaded", timeout=45_000)
                await self._settle_archive_page(page)
                return RenderedPage(html=await page.content(), final_url=page.url)
            finally:
                await context.close()
        finally:
            await browser.close()

    async def _new_context(self, browser: Browser) -> BrowserContext:
        return await browser.new_context(
            locale=self._settings.browser_locale,
            timezone_id=self._settings.browser_timezone,
            user_agent=self._settings.http_user_agent,
            viewport={"width": 1440, "height": 960},
        )

    async def _settle_page(self, page: Page) -> None:
        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except TimeoutError:
            await page.wait_for_timeout(2_000)

    async def _settle_archive_page(self, page: Page) -> None:
        await self._settle_page(page)
        title = await page.title()
        body_text = await page.locator("body").inner_text(timeout=10_000)
        if looks_like_archive_challenge_page(title, body_text, page.url):
            await self._click_archive_recaptcha(page)
            await self._settle_page(page)
            title = await page.title()
            body_text = await page.locator("body").inner_text(timeout=10_000)
            if looks_like_archive_challenge_page(title, body_text, page.url):
                raise TimeoutError("Archive challenge page persisted after retry")
        if looks_like_archive_listing_page(title, body_text, page.url):
            listing_url = page.url
            await self._open_latest_archive_snapshot(page)
            await self._settle_page(page)
            title = await page.title()
            body_text = await page.locator("body").inner_text(timeout=10_000)
            if page.url == listing_url and looks_like_archive_listing_page(
                title, body_text, page.url
            ):
                raise TimeoutError("Archive listing page did not open a snapshot")
        if looks_like_archive_no_results_page(title, body_text, page.url):
            raise TimeoutError("Archive lookup returned no results")

    async def _click_archive_recaptcha(self, page: Page) -> None:
        anchor_frame = next(
            (frame for frame in page.frames if "recaptcha/api2/anchor" in frame.url),
            None,
        )
        if anchor_frame is None:
            return
        anchor = anchor_frame.locator("#recaptcha-anchor")
        if await anchor.count() == 0:
            return
        await anchor.click(timeout=10_000, force=True)
        await page.wait_for_timeout(8_000)

    async def _open_latest_archive_snapshot(self, page: Page) -> None:
        snapshot_link = page.locator("#CONTENT .TEXT-BLOCK a[href^='https://archive.is/']").first
        if await snapshot_link.count() == 0:
            snapshot_link = page.locator("#CONTENT a[href^='https://archive.is/']").first
        if await snapshot_link.count() == 0:
            return
        snapshot_url = await snapshot_link.get_attribute("href")
        if snapshot_url:
            await page.goto(snapshot_url, wait_until="domcontentloaded", timeout=45_000)


def archive_lookup_url(url: str) -> str:
    """Build the archive.is lookup URL for an article."""
    return f"{ARCHIVE_BASE_URL}{url}"


def archive_lookup_urls(url: str) -> tuple[str, ...]:
    """Build archive lookup URLs, including a queryless fallback when useful."""
    lookup_urls = [archive_lookup_url(url)]
    parsed = urlsplit(url)
    if parsed.query:
        queryless_url = urlunsplit(parsed._replace(query=""))
        queryless_lookup_url = archive_lookup_url(queryless_url)
        if queryless_lookup_url not in lookup_urls:
            lookup_urls.append(queryless_lookup_url)
    return tuple(lookup_urls)


def looks_like_archive_challenge_page(title: str, body_text: str, url: str) -> bool:
    """Return whether the current archive page is blocked by a CAPTCHA gate."""
    lowered = f"{title}\n{body_text}\n{url}".lower()
    markers = (
        "please complete the security check to access archive.is",
        "why do i have to complete a captcha",
        "google.com/recaptcha",
        "one more step",
    )
    return any(marker in lowered for marker in markers)


def looks_like_archive_listing_page(title: str, body_text: str, url: str) -> bool:
    """Return whether archive.is is showing the snapshot listing page."""
    parsed = urlparse(url)
    lowered = f"{title}\n{body_text}\n{parsed.path}".lower()
    return (
        "archive.today" in lowered
        and "list of urls, ordered from newer to older" in lowered
        and parsed.netloc.lower() == "archive.is"
    )


def looks_like_archive_no_results_page(title: str, body_text: str, url: str) -> bool:
    """Return whether archive.is is showing a search page with no snapshots."""
    parsed = urlparse(url)
    lowered = f"{title}\n{body_text}\n{parsed.path}".lower()
    return (
        "archive.today" in lowered
        and "webpage capture" in lowered
        and "no results" in lowered
        and parsed.netloc.lower() == "archive.is"
    )
