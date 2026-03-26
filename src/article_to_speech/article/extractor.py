from __future__ import annotations

from article_to_speech.article.archive_parser import parse_supported_archive_article
from article_to_speech.core.models import ResolvedArticle


class ArticleExtractor:
    def extract(self, *, url: str, final_url: str, html: str) -> ResolvedArticle | None:
        """Parse a supported archive snapshot into a structured article."""
        return parse_supported_archive_article(url=url, final_url=final_url, html=html)

    def is_incomplete(self, article: ResolvedArticle) -> bool:
        """Return whether the parsed article body is empty."""
        return not article.body_text.strip()
