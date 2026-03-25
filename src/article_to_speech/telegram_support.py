from __future__ import annotations

from urllib.parse import urlparse

from article_to_speech.core.models import ResolvedArticle


def build_caption(article: ResolvedArticle) -> str:
    """Build the Telegram audio caption for a resolved article."""
    parts = [article.title]
    if article.source:
        parts.append(article.source)
    if article.author:
        parts.append(article.author)
    caption = " | ".join(parts[:3])
    if _is_archive_snapshot_url(article.final_url):
        return f"{caption}\n{article.final_url}"
    return caption


def build_intermediate_article_link(article: ResolvedArticle) -> str | None:
    """Build an intermediate non-snapshot link message when resolution used an archive URL."""
    if not _is_archive_snapshot_url(article.final_url):
        return None
    url = next(
        (
            candidate
            for candidate in (article.canonical_url, article.original_url)
            if candidate and not _is_archive_snapshot_url(candidate)
        ),
        None,
    )
    if url is None:
        return None
    return f"Article link:\n{url}"


def _is_archive_snapshot_url(url: str) -> bool:
    """Return whether the URL points to a supported archive snapshot host."""
    host = urlparse(url).netloc.lower()
    return host in {"archive.is", "archive.today", "archive.ph"}
