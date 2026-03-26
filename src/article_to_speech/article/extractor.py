from __future__ import annotations

import json
import re
from dataclasses import dataclass

import trafilatura
from bs4 import BeautifulSoup
from bs4.element import Tag
from readability import Document

from article_to_speech.article.extractor_support import (
    _extract_archive_replay_text,
    _extract_archive_story_text,
    _extract_body_author,
    _extract_body_published,
    _extract_document_headline,
    _normalize_text,
    _preferred_source,
    sanitize_html,
    trim_extracted_body,
)
from article_to_speech.article.metadata import extract_metadata
from article_to_speech.core.models import ResolvedArticle

PAYWALL_MARKERS = (
    "subscribe to continue",
    "abonnieren",
    "jetzt weiterlesen",
    "for subscribers",
    "continue reading with trial",
)


@dataclass(slots=True, frozen=True)
class ExtractionAttempt:
    source_name: str
    body_text: str


class ArticleExtractor:
    def extract(self, *, url: str, final_url: str, html: str) -> ResolvedArticle | None:
        """Extract the fullest usable article body from an HTML document."""
        sanitized_html = sanitize_html(html)
        soup = BeautifulSoup(sanitized_html, "lxml")
        article_root = soup.select_one("article#story") or soup.find("article")
        metadata = extract_metadata(soup, final_url)
        headline = _extract_document_headline(article_root or soup)
        best = _best_attempt(soup, sanitized_html, final_url)
        if best is None:
            return None
        return _build_resolved_article(url, final_url, metadata, article_root, headline, best, soup)

    def is_incomplete(self, article: ResolvedArticle) -> bool:
        """Return whether the extracted article still looks like a teaser or paywall stub."""
        lowered = article.body_text.lower()
        return not _looks_complete(article.body_text) or any(
            marker in lowered for marker in PAYWALL_MARKERS
        )


def _best_attempt(soup: BeautifulSoup, html: str, final_url: str) -> ExtractionAttempt | None:
    attempts = [
        _archive_story_attempt(soup),
        _archive_replay_attempt(soup),
        _extract_ld_json_article_body(soup),
        _extract_json_article_body(soup),
        _extract_container_text(soup, "article", ["p", "h2", "li"], "article_tag"),
        _extract_trafilatura_text(html, final_url),
        _extract_readability_text(html),
        _extract_container_text(soup, "main", ["p"], "main_tag"),
    ]
    usable = [attempt for attempt in attempts if attempt and _looks_complete(attempt.body_text)]
    if not usable:
        return None
    return max(usable, key=lambda attempt: len(attempt.body_text))


def _archive_story_attempt(soup: BeautifulSoup) -> ExtractionAttempt | None:
    cleaned = _extract_archive_story_text(soup)
    if not cleaned:
        return None
    return ExtractionAttempt("archive_story", cleaned)


def _archive_replay_attempt(soup: BeautifulSoup) -> ExtractionAttempt | None:
    cleaned = _extract_archive_replay_text(soup)
    if not cleaned:
        return None
    return ExtractionAttempt("archive_replay", cleaned)


def _extract_ld_json_article_body(soup: BeautifulSoup) -> ExtractionAttempt | None:
    for block in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = block.string or block.text
        if not text:
            continue
        for payload in _load_possible_json(text):
            for article_object in _iter_article_objects(payload):
                body_text = article_object.get("articleBody")
                if isinstance(body_text, str):
                    cleaned = _normalize_text(body_text)
                    if cleaned:
                        return ExtractionAttempt("ld_json_article_body", cleaned)
    return None


def _extract_json_article_body(soup: BeautifulSoup) -> ExtractionAttempt | None:
    for block in soup.find_all("script"):
        text = block.string or block.text
        if not text or "articleBody" not in text:
            continue
        match = re.search(r'"articleBody"\s*:\s*"(.+?)"', text, re.DOTALL)
        if match is None:
            continue
        try:
            body_text = json.loads(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            continue
        cleaned = _normalize_text(body_text)
        if cleaned:
            return ExtractionAttempt("embedded_json_article_body", cleaned)
    return None


def _extract_container_text(
    soup: BeautifulSoup,
    tag_name: str,
    paragraph_tags: list[str],
    source_name: str,
) -> ExtractionAttempt | None:
    container = soup.find(tag_name)
    if container is None:
        return None
    paragraphs = [
        paragraph.get_text(" ", strip=True) for paragraph in container.find_all(paragraph_tags)
    ]
    cleaned = _normalize_text("\n\n".join(paragraphs))
    if not cleaned:
        return None
    return ExtractionAttempt(source_name, cleaned)


def _extract_trafilatura_text(html: str, url: str) -> ExtractionAttempt | None:
    extracted = trafilatura.extract(
        html,
        url=url,
        favor_precision=True,
        include_comments=False,
        include_tables=False,
    )
    cleaned = _normalize_text(extracted or "")
    if not cleaned:
        return None
    return ExtractionAttempt("trafilatura", cleaned)


def _extract_readability_text(html: str) -> ExtractionAttempt | None:
    summary_html = Document(html).summary(html_partial=True)
    soup = BeautifulSoup(summary_html, "lxml")
    return _extract_container_text(soup, "body", ["p", "h2", "li"], "readability")


def _looks_complete(text: str) -> bool:
    if not text:
        return False
    if len(text.split()) < 250:
        return False
    lowered = text.lower()
    return not any(marker in lowered for marker in PAYWALL_MARKERS)


def _guess_title_from_body(text: str) -> str | None:
    first_line = text.splitlines()[0].strip() if text else ""
    if 8 <= len(first_line) <= 140:
        return first_line
    return None


def _load_possible_json(text: str) -> list[object]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        return payload
    return [payload]


def _iter_article_objects(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, dict):
        payload_type = payload.get("@type")
        if payload_type in {"NewsArticle", "Article", "ReportageNewsArticle"}:
            return [payload]
        graph = payload.get("@graph")
        if isinstance(graph, list):
            objects: list[dict[str, object]] = []
            for item in graph:
                objects.extend(_iter_article_objects(item))
            return objects
    return []


def _build_resolved_article(
    url: str,
    final_url: str,
    metadata: dict[str, str | None],
    article_root: Tag | BeautifulSoup | None,
    headline: str | None,
    best: ExtractionAttempt,
    soup: BeautifulSoup,
) -> ResolvedArticle:
    metadata_title = headline or metadata["title"]
    title = metadata_title or _guess_title_from_body(best.body_text) or final_url
    return ResolvedArticle(
        canonical_url=url,
        original_url=url,
        final_url=final_url,
        title=title,
        source=_preferred_source(metadata["source"], soup),
        author=metadata["author"] or _extract_body_author(article_root),
        published_at=metadata["published_at"] or _extract_body_published(article_root),
        body_text=trim_extracted_body(best.body_text, metadata_title),
        trace=(best.source_name,),
    )
