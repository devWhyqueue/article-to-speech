from __future__ import annotations

import logging
from dataclasses import replace

from article_to_speech.article.extractor import ArticleExtractor
from article_to_speech.article.source_detection import detect_supported_source
from article_to_speech.browser.fetcher import BrowserPageFetcher
from article_to_speech.core.config import Settings
from article_to_speech.core.exceptions import ArchivedPaywallError, ArticleResolutionError
from article_to_speech.core.models import ResolvedArticle
from article_to_speech.core.urls import normalize_url

LOGGER = logging.getLogger(__name__)


class ArticleResolver:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._extractor = ArticleExtractor()
        self._browser_fetcher = BrowserPageFetcher(settings)

    async def close(self) -> None:
        return None

    async def resolve(self, input_url: str) -> ResolvedArticle:
        normalized_url = normalize_url(input_url)
        source = detect_supported_source(normalized_url)
        if source is None:
            raise ArticleResolutionError(
                f"Unsupported article source for archive-only extraction: {normalized_url}"
            )

        LOGGER.info(
            "render_archive_article",
            extra={"context": {"url": normalized_url, "source": source.slug}},
        )
        try:
            rendered_page = await self._browser_fetcher.render_archive_html(normalized_url)
        except Exception as error:  # noqa: BLE001
            raise ArticleResolutionError(
                f"Failed to load archive snapshot for {normalized_url}: {error}"
            ) from error

        article = self._extractor.extract(
            url=normalized_url,
            final_url=rendered_page.final_url,
            html=rendered_page.html,
        )
        if article is not None and article.paywalled:
            raise ArchivedPaywallError("Archive snapshot still shows the SPIEGEL+ paywall")
        if article is None or self._extractor.is_incomplete(article):
            raise ArticleResolutionError(
                f"Failed to parse supported archive snapshot for {normalized_url}"
            )
        return replace(article, trace=tuple(article.trace) + ("archive_render",))
