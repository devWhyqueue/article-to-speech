from __future__ import annotations

import re

from bs4 import BeautifulSoup
from bs4.element import Tag


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


def _normalize_text(text: str) -> str:
    lines = []
    for line in text.replace("\r", "\n").splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n\n".join(lines).strip()


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
