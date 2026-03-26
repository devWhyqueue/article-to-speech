from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from article_to_speech.article.archive_replay import (
    extract_archive_replay_text,
)


def sanitize_html(html: str) -> str:
    """Remove consent and privacy overlays before extraction."""
    soup = BeautifulSoup(html, "lxml")
    selectors = [
        "#fides-banner",
        "#fides-modal",
        "#fides-embed-container",
        "#fides-consent-content",
        "[id*='fides']",
        "[class*='fides']",
        "[id*='consent']",
        "[class*='consent']",
        "[id*='privacy']",
        "[class*='privacy']",
        "[aria-label*='privacy' i]",
        "[aria-label*='consent' i]",
        "[role='dialog']",
    ]
    for selector in selectors:
        for node in soup.select(selector):
            node.decompose()
    return str(soup)


def trim_extracted_body(text: str, title: str | None) -> str:
    """Drop leading archive modules and trailing recommendation blocks."""
    trimmed = text
    if title:
        title_index = trimmed.find(title)
        if title_index > 0:
            trimmed = trimmed[title_index:]
    for marker in (
        "\n\nRelated Content\n\n",
        "\n\nEditors’ Picks\n\n",
        "\n\nEditors' Picks\n\n",
        "\n\nMore on NYTimes.com\n\n",
    ):
        marker_index = trimmed.find(marker)
        if marker_index != -1:
            trimmed = trimmed[:marker_index]
    return trimmed.strip()


def _extract_document_headline(container: Tag | BeautifulSoup | None) -> str | None:
    if container is None:
        return None
    heading = container.find(["h1", "h2"])
    if heading is None:
        return None
    text = _normalize_text(heading.get_text(" ", strip=True))
    return text or None


def _preferred_source(current_source: str | None, soup: BeautifulSoup) -> str | None:
    if current_source and current_source.lower() != "archive.is":
        return current_source
    title_tag = soup.find("title")
    title_text = title_tag.get_text(" ", strip=True) if title_tag else ""
    if " - " not in title_text:
        return current_source
    suffix = title_text.rsplit(" - ", 1)[-1].strip()
    return suffix or current_source


def _extract_body_author(article_root: Tag | BeautifulSoup | None) -> str | None:
    if article_root is None:
        return None
    text = _normalize_text(article_root.get_text(" ", strip=True))
    match = re.search(r"\bBy ([A-Z][A-Za-z.\- ]+?)(?: Reporting from| See more on:|$)", text)
    if match is None:
        return None
    return _normalize_text(match.group(1))


def _extract_body_published(article_root: Tag | BeautifulSoup | None) -> str | None:
    if article_root is None:
        return None
    text = article_root.get_text("\n", strip=True)
    match = re.search(r"\b([A-Z][a-z]+ \d{1,2}, \d{4})\b", text)
    if match is None:
        return None
    return match.group(1)


def _extract_archive_story_text(soup: BeautifulSoup) -> str | None:
    article = soup.select_one("article#story")
    if article is None:
        return None
    headline = _extract_document_headline(article)
    if not headline:
        return None
    parts: list[str] = [headline]
    _append_archive_summary(parts, article, headline)
    body_section = _first_story_body_section(article, headline)
    if body_section is None:
        return None
    for block in body_section.find_all(recursive=False):
        block_text = _normalize_text(block.get_text(" ", strip=True))
        if _looks_like_story_paragraph(block_text):
            parts.append(block_text)
    cleaned = _normalize_text("\n\n".join(parts))
    return cleaned or None


def _extract_archive_replay_text(soup: BeautifulSoup) -> str | None:
    return extract_archive_replay_text(
        soup,
        normalize_text=_normalize_text,
        extract_document_headline=_extract_document_headline,
    )


def _normalize_text(text: str) -> str:
    lines = []
    for line in text.replace("\r", "\n").splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n\n".join(lines).strip()


def guess_title_from_body(text: str) -> str | None:
    """Return a plausible title candidate from the first extracted line."""
    first_line = text.splitlines()[0].strip() if text else ""
    if 8 <= len(first_line) <= 140:
        return first_line
    return None


def load_possible_json(text: str) -> list[object]:
    """Parse a JSON blob that may contain a single payload or a list."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        return payload
    return [payload]


def iter_article_objects(payload: object) -> list[dict[str, object]]:
    """Walk a JSON-LD payload and return article-like objects."""
    if isinstance(payload, dict):
        payload_type = payload.get("@type")
        if payload_type in {"NewsArticle", "Article", "ReportageNewsArticle"}:
            return [payload]
        graph = payload.get("@graph")
        if isinstance(graph, list):
            objects: list[dict[str, object]] = []
            for item in graph:
                objects.extend(iter_article_objects(item))
            return objects
    return []


def _append_archive_summary(parts: list[str], article: Tag, headline: str) -> None:
    header = article.find("header")
    if header is None:
        return
    summary = header.find(class_="article-summary")
    summary_text = _normalize_text(summary.get_text(" ", strip=True)) if summary else ""
    if summary_text and summary_text != headline:
        parts.append(summary_text)


def _first_story_body_section(article: Tag, headline: str) -> Tag | None:
    for child in article.find_all(recursive=False):
        if child.name != "section":
            continue
        text = _normalize_text(child.get_text(" ", strip=True))
        if headline in text or len(text.split()) >= 120:
            return child
    return article.find("section")


def _looks_like_story_paragraph(text: str) -> bool:
    if not text or len(text.split()) < 12:
        return False
    lowered = text.lower()
    noise_markers = (
        "share full article",
        "supported by",
        "skip advertisement",
        "related content",
        "our coverage of",
        "more in politics",
    )
    if any(marker in lowered for marker in noise_markers):
        return False
    return any(punctuation in text for punctuation in (".", "?", "!", ";"))


def has_paywall_signals(soup: BeautifulSoup, html: str, final_url: str) -> bool:
    """Return whether the current non-archive document explicitly signals a paywall."""
    if urlparse(final_url).netloc.lower() in {"archive.is", "archive.today", "archive.ph"}:
        return False
    if soup.select_one("html[data-is-truncated-by-paywall], #paywall, [data-paywall]") is not None:
        return True
    lowered_html = html.lower()
    if any(marker in lowered_html for marker in ("abopflichtiger inhalt", "zeit+", "z+")):
        return True
    for block in soup.find_all("script"):
        text = block.string or block.text
        if text and re.search(r'"isAccessibleForFree"\s*:\s*"?(false|0)"?', text, re.IGNORECASE):
            return True
    return False
