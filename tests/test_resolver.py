from __future__ import annotations

from pathlib import Path
from typing import cast

import httpx

from article_to_speech.article.extractor import ArticleExtractor
from article_to_speech.article.resolver import ArticleResolver
from article_to_speech.browser.fetcher import BrowserPageFetcher, RenderedPage
from article_to_speech.core.config import Settings
from article_to_speech.core.models import ResolvedArticle


class StubExtractor:
    def extract(self, *, url: str, final_url: str, html: str) -> ResolvedArticle | None:
        if "full article" not in html:
            return None
        return ResolvedArticle(
            canonical_url=url,
            original_url=url,
            final_url=final_url,
            title="Example",
            source=None,
            author=None,
            published_at=None,
            body_text="full article body",
            trace=("stub",),
        )

    def is_incomplete(self, article: ResolvedArticle) -> bool:
        return False


class StubBrowserFetcher:
    def __init__(self, browser_html: str = "browser teaser") -> None:
        self.browser_html = browser_html
        self.rendered_urls: list[str] = []

    async def render_archive_html(self, url: str) -> RenderedPage:
        self.rendered_urls.append(url)
        return RenderedPage(html=self.browser_html, final_url="https://archive.is/example")


class StubClient:
    def __init__(self, responses: dict[str, httpx.Response]) -> None:
        self._responses = responses
        self.requested_urls: list[str] = []

    async def get(self, url: str) -> httpx.Response:
        self.requested_urls.append(url)
        response = self._responses[url]
        if response.is_error:
            raise httpx.HTTPStatusError("status error", request=response.request, response=response)
        return response

    async def aclose(self) -> None:
        return None


def _settings() -> Settings:
    return Settings(
        telegram_bot_token="token",
        telegram_allowed_chat_id=1,
        chatgpt_project_name="project",
        runtime_root=Path("/tmp/article-to-speech"),
        browser_profile_dir=Path("/tmp/article-to-speech/profile"),
        state_db_path=Path("/tmp/article-to-speech/state/jobs.sqlite3"),
        artifacts_dir=Path("/tmp/article-to-speech/artifacts"),
        diagnostics_dir=Path("/tmp/article-to-speech/diagnostics"),
        browser_display=":99",
        chatgpt_browser_headless=False,
        browser_locale="en-US",
        browser_timezone=None,
        chatgpt_proxy_url=None,
        chatgpt_project_url=None,
        archive_proxy_urls=(),
        archive_proxy_list_url=None,
        article_retry_count=3,
    )


def _response(url: str, status_code: int, body: str) -> httpx.Response:
    request = httpx.Request("GET", url)
    return httpx.Response(status_code, text=body, request=request)


async def test_resolve_uses_archive_render_when_direct_extraction_is_incomplete() -> None:
    resolver = ArticleResolver(_settings())
    browser_fetcher = StubBrowserFetcher("full article from browser")
    client = StubClient(
        {
            "https://example.com/story": _response("https://example.com/story", 200, "teaser"),
        }
    )
    resolver._extractor = cast(ArticleExtractor, StubExtractor())
    resolver._browser_fetcher = cast(BrowserPageFetcher, browser_fetcher)
    resolver._client = cast(httpx.AsyncClient, client)

    article = await resolver.resolve("https://example.com/story")

    assert article.trace == ("stub", "archive_render")
    assert client.requested_urls == ["https://example.com/story"]
    assert browser_fetcher.rendered_urls == ["https://example.com/story"]


async def test_resolve_falls_back_to_archive_render_after_direct_http_error() -> None:
    resolver = ArticleResolver(_settings())
    browser_fetcher = StubBrowserFetcher(browser_html="full article from browser")
    client = StubClient(
        {
            "https://example.com/story": _response(
                "https://example.com/story",
                429,
                "rate limited",
            ),
        }
    )
    resolver._extractor = cast(ArticleExtractor, StubExtractor())
    resolver._browser_fetcher = cast(BrowserPageFetcher, browser_fetcher)
    resolver._client = cast(httpx.AsyncClient, client)

    article = await resolver.resolve("https://example.com/story")

    assert article.trace == ("stub", "archive_render")
    assert browser_fetcher.rendered_urls == ["https://example.com/story"]
