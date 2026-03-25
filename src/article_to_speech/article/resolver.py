from __future__ import annotations

import logging
from dataclasses import replace

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

from article_to_speech.article.extractor import ArticleExtractor
from article_to_speech.browser.fetcher import BrowserPageFetcher
from article_to_speech.core.config import Settings
from article_to_speech.core.exceptions import ArticleResolutionError
from article_to_speech.core.models import ResolvedArticle
from article_to_speech.core.urls import normalize_url

LOGGER = logging.getLogger(__name__)


class ArticleResolver:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._extractor = ArticleExtractor()
        self._browser_fetcher = BrowserPageFetcher(settings)
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=settings.article_timeout_seconds,
            headers={"User-Agent": settings.http_user_agent},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def resolve(self, input_url: str) -> ResolvedArticle:
        normalized_url = normalize_url(input_url)
        errors: list[str] = []

        try:
            response = await self._get(normalized_url)
            article = self._extractor.extract(
                url=normalized_url,
                final_url=str(response.url),
                html=response.text,
            )
            if article and not self._extractor.is_incomplete(article):
                return replace(article, trace=tuple(article.trace) + ("direct",))
            errors.append("direct: incomplete extraction")
        except (httpx.HTTPError, ArticleResolutionError) as error:
            errors.append(f"direct: {error}")

        try:
            rendered_page = await self._browser_fetcher.render_archive_html(normalized_url)
            article = self._extractor.extract(
                url=normalized_url,
                final_url=rendered_page.final_url,
                html=rendered_page.html,
            )
            if article and not self._extractor.is_incomplete(article):
                return replace(article, trace=tuple(article.trace) + ("archive_render",))
            errors.append("archive_render: incomplete extraction")
        except Exception as error:  # noqa: BLE001
            errors.append(f"archive_render: {error}")

        detail = "; ".join(errors[-5:])
        raise ArticleResolutionError(
            f"Failed to resolve a full article for {normalized_url}. {detail}"
        )

    async def _get(self, url: str) -> httpx.Response:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._settings.article_retry_count),
            wait=wait_exponential(multiplier=1, min=1, max=6),
            retry=retry_if_exception(_is_retryable_http_error),
            reraise=True,
        ):
            with attempt:
                LOGGER.info(
                    "fetch_article_attempt",
                    extra={
                        "context": {
                            "url": url,
                            "attempt": attempt.retry_state.attempt_number,
                        }
                    },
                )
                response = await self._client.get(url)
                response.raise_for_status()
                return response
        raise ArticleResolutionError(f"Unreachable URL: {url}")


def _is_retryable_http_error(error: BaseException) -> bool:
    if not isinstance(error, httpx.HTTPError):
        return False
    if isinstance(error, httpx.HTTPStatusError):
        return (
            error.response.status_code
            in {
                httpx.codes.REQUEST_TIMEOUT,
                httpx.codes.CONFLICT,
                httpx.codes.TOO_EARLY,
                httpx.codes.TOO_MANY_REQUESTS,
            }
            or error.response.status_code >= 500
        )
    return True
