from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from article_to_speech.article.extractor import ArticleExtractor
from article_to_speech.article.resolver import ArticleResolver
from article_to_speech.article.source_detection import detect_supported_source
from article_to_speech.browser.fetcher import BrowserPageFetcher, RenderedPage
from article_to_speech.core.config import Settings
from article_to_speech.core.exceptions import ArchivedPaywallError, ArticleResolutionError
from article_to_speech.core.models import ResolvedArticle


class StubExtractor:
    def extract(self, *, url: str, final_url: str, html: str) -> ResolvedArticle | None:
        if "article" not in html:
            return None
        source = detect_supported_source(url)
        source_slug = source.slug if source is not None else "unknown"
        return ResolvedArticle(
            canonical_url=url,
            original_url=url,
            final_url=final_url,
            title="Example",
            subtitle="Subtitle",
            source="DIE ZEIT",
            author="Reporter",
            published_at="2026-03-26",
            body_text="Paragraph one.",
            trace=(source_slug,),
        )

    def is_incomplete(self, article: ResolvedArticle) -> bool:
        return False


class StubBrowserFetcher:
    def __init__(self, browser_html: str = "article body") -> None:
        self.browser_html = browser_html
        self.rendered_urls: list[str] = []

    async def render_archive_html(self, url: str) -> RenderedPage:
        self.rendered_urls.append(url)
        return RenderedPage(html=self.browser_html, final_url="https://archive.is/example")


def _settings() -> Settings:
    return Settings(
        telegram_bot_token="token",
        telegram_allowed_chat_id=1,
        google_application_credentials=Path("/tmp/article-to-speech/service-account.json"),
        runtime_root=Path("/tmp/article-to-speech"),
        state_db_path=Path("/tmp/article-to-speech/state/jobs.sqlite3"),
        artifacts_dir=Path("/tmp/article-to-speech/artifacts"),
        diagnostics_dir=Path("/tmp/article-to-speech/diagnostics"),
        browser_headless=False,
        browser_locale="en-US",
        browser_timezone=None,
        archive_proxy_urls=(),
        archive_proxy_list_url=None,
        article_retry_count=3,
    )


async def test_resolve_uses_archive_render_for_supported_source() -> None:
    resolver = ArticleResolver(_settings())
    browser_fetcher = StubBrowserFetcher()
    resolver._extractor = cast(ArticleExtractor, StubExtractor())
    resolver._browser_fetcher = cast(BrowserPageFetcher, browser_fetcher)

    article = await resolver.resolve(
        "https://www.zeit.de/2026/14/karin-prien-bundesfrauenministerin-gewalthilfegesetz-digitale-gewalt"
    )

    assert article.trace == ("zeit", "archive_render")
    assert browser_fetcher.rendered_urls == [
        "https://www.zeit.de/2026/14/karin-prien-bundesfrauenministerin-gewalthilfegesetz-digitale-gewalt"
    ]


async def test_resolve_uses_archive_render_for_supported_spektrum_source() -> None:
    resolver = ArticleResolver(_settings())
    browser_fetcher = StubBrowserFetcher()
    resolver._extractor = cast(ArticleExtractor, StubExtractor())
    resolver._browser_fetcher = cast(BrowserPageFetcher, browser_fetcher)

    article = await resolver.resolve(
        "https://www.spektrum.de/news/was-ein-schimpansen-buergerkrieg-ueber-menschliche-konflikte-verraet/2319030"
    )

    assert article.trace == ("spektrum", "archive_render")
    assert browser_fetcher.rendered_urls == [
        "https://www.spektrum.de/news/was-ein-schimpansen-buergerkrieg-ueber-menschliche-konflikte-verraet/2319030"
    ]


async def test_resolve_rejects_unsupported_source() -> None:
    resolver = ArticleResolver(_settings())

    with pytest.raises(ArticleResolutionError, match="Unsupported article source"):
        await resolver.resolve("https://example.com/story")


async def test_resolve_surfaces_archive_render_errors() -> None:
    resolver = ArticleResolver(_settings())

    class FailingBrowserFetcher:
        async def render_archive_html(self, url: str) -> RenderedPage:
            raise RuntimeError("Archive lookup returned no results")

    resolver._browser_fetcher = cast(BrowserPageFetcher, FailingBrowserFetcher())

    with pytest.raises(ArticleResolutionError, match="Archive lookup returned no results"):
        await resolver.resolve("https://www.faz.net/aktuell/politik/example.html")


async def test_resolve_surfaces_archived_paywall_errors() -> None:
    resolver = ArticleResolver(_settings())

    class PaywalledExtractor:
        def extract(self, *, url: str, final_url: str, html: str) -> ResolvedArticle | None:
            raise ArchivedPaywallError("Archive snapshot still shows the SPIEGEL+ paywall")

        def is_incomplete(self, article: ResolvedArticle) -> bool:
            return False

    resolver._extractor = cast(ArticleExtractor, PaywalledExtractor())
    resolver._browser_fetcher = cast(BrowserPageFetcher, StubBrowserFetcher())

    with pytest.raises(ArchivedPaywallError, match="SPIEGEL\\+ paywall"):
        await resolver.resolve("https://www.spiegel.de/politik/deutschland/example.html")
