from __future__ import annotations

import re
from typing import Final

from bs4.element import Tag

from article_to_speech.article import _normalize_archive_text, _normalize_publication_date
from article_to_speech.article_helpers import SourceParserConfig

DROP_SELECTORS: Final[tuple[str, ...]] = (
    "aside",
    "nav",
    "footer",
    "button",
    "form",
    "dialog",
    "script",
    "style",
    "noscript",
    "[id*='comment']",
    "[class*='comment']",
    "[aria-label*='Kommentar' i]",
    "[aria-label*='comments' i]",
    "[aria-label*='Newsletter' i]",
    "[aria-label*='Mehr zum Thema' i]",
    "[aria-label*='Seitennavigation' i]",
)
BODY_TAGS: Final[tuple[str, ...]] = ("div", "p", "blockquote", "h2", "h3")
HEADING_TAGS: Final[set[str]] = {"h2", "h3"}
QUOTE_TAGS: Final[set[str]] = {"blockquote"}


def extract_published_at(flat_text: str) -> str | None:
    """Return the normalized publication date from a flattened article text blob."""
    for pattern in (
        r"\b\d{1,2}\.\d{1,2}\.\d{4}, \d{2}[:.]\d{2}\b",
        r"\b\d{1,2}\.\d{1,2}\.\d{4}\b",
        r"\b\d{1,2}\.\s+[A-ZÄÖÜa-zäöü]+\s+\d{4}, \d{1,2}:\d{2}\s+Uhr\b",
        r"\b[A-Z][a-z]+\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}\s+[ap]\.m\. ET\b",
    ):
        match = re.search(pattern, flat_text)
        if match is not None:
            return _normalize_date(match.group(0))
    return None


def normalize_archive_text(text: str) -> str:
    """Normalize archive snapshot text into stable, newline-preserving plain text."""
    return _normalize_archive_text(text)


def _contains_zeit_page_heading(article: Tag) -> bool:
    return any(
        node.name in HEADING_TAGS
        and "seite" in normalize_archive_text(node.get_text(" ", strip=True)).lower()
        for node in article.find_all(HEADING_TAGS)
    )


def _is_stop_block(node: Tag, text: str, config: SourceParserConfig) -> bool:
    lowered = text.lower()
    if any(lowered == marker or lowered.startswith(f"{marker} ") for marker in config.stop_markers):
        return True
    return any(marker in lowered for marker in config.stop_markers) and (
        node.name in HEADING_TAGS or len(text.split()) <= 4
    )


def _is_metadata_line(text: str, author: str | None) -> bool:
    lowered = text.lower()
    if author and text == author:
        return True
    return any(
        lowered.startswith(prefix)
        for prefix in (
            "von ",
            "by ",
            "kommentar von ",
            "interview:",
            "aktualisiert am",
            "26.03.2026",
            "26. märz 2026",
            "march 26, 2026",
        )
    )


def _looks_like_body_paragraph(text: str) -> bool:
    return len(text.split()) >= 12 and any(mark in text for mark in (".", "?", "!", "”", '"'))


def _looks_like_caption(text: str) -> bool:
    lowered = text.lower()
    if any(
        marker in lowered for marker in ("foto:", "credit...", "/ ap", "/ dpa", "/ sf", "bild:")
    ):
        return True
    if text.startswith("©"):
        return True
    if (
        any(marker in lowered for marker in ("(ausschnitt)", "getty images", "getty", "istock"))
        and len(text.split()) <= 28
    ):
        return True
    credit_markers = (
        "getty",
        "istock",
        "picture alliance",
        "imago",
        "shutterstock",
        "eyeem",
        "afp",
        "reuters",
    )
    if sum(marker in lowered for marker in credit_markers) >= 2 and len(text.split()) <= 28:
        return True
    return text.endswith(("AP", "dpa", "picture alliance")) and len(text.split()) <= 20


def _contains_noise(text: str, config: SourceParserConfig) -> bool:
    return any(marker in text.lower() for marker in config.noise_markers)


def _render_markdown_block(node: Tag, text: str) -> str:
    if node.name in HEADING_TAGS and 2 <= len(text.split()) <= 16:
        return f"## {text}"
    if node.name in QUOTE_TAGS:
        return f"> {text}"
    return text


def _extract_spiegel_subtitle_candidate(
    article: Tag,
    title: str,
    config: SourceParserConfig,
) -> str | None:
    heading = next(
        (
            node
            for node in article.find_all("h2")
            if len(normalize_archive_text(node.get_text(" ", strip=True)).split()) >= 8
        ),
        None,
    )
    if heading is None:
        return None
    for node in heading.find_all_next(("div", "p")):
        if article not in node.parents:
            continue
        text = normalize_archive_text(node.get_text(" ", strip=True))
        if not text or text == title or _contains_noise(text, config) or _looks_like_caption(text):
            continue
        if len(text.split()) >= 10 and any(mark in text for mark in '.!?”“"'):
            return text
    return None


def _normalize_date(raw_value: str) -> str:
    return _normalize_publication_date(raw_value)
