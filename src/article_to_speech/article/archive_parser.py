from __future__ import annotations

import re

from bs4 import BeautifulSoup
from bs4.element import Tag

from article_to_speech.article.parser_config import (
    BODY_TAGS,
    CONFIG_BY_SLUG,
    DROP_SELECTORS,
    HEADING_TAGS,
    QUOTE_TAGS,
    SourceParserConfig,
    extract_published_at,
    normalize_archive_text,
)
from article_to_speech.article.source_detection import detect_supported_source
from article_to_speech.core.models import ResolvedArticle


def parse_supported_archive_article(url: str, final_url: str, html: str) -> ResolvedArticle | None:
    """Parse one supported archive snapshot into a structured article."""
    source = detect_supported_source(url)
    if source is None:
        return None
    config = CONFIG_BY_SLUG[source.slug]
    soup = BeautifulSoup(html, "lxml")
    article = _select_main_article(soup)
    if article is None:
        return None
    article = _clone_article(article)
    _drop_noise_nodes(article)
    return _build_article(url, final_url, soup, article, config)


def _build_article(
    url: str,
    final_url: str,
    soup: BeautifulSoup,
    article: Tag,
    config: SourceParserConfig,
) -> ResolvedArticle | None:
    title = _extract_title(article) or _extract_meta_title(soup, config)
    if title is None:
        return None
    flat_text = normalize_archive_text(article.get_text("\n", strip=True))
    subtitle = _extract_subtitle(article, title, config)
    author = _extract_author(flat_text, config)
    published_at = extract_published_at(flat_text)
    body_text = _extract_markdown_body(article, title, subtitle, author, published_at, config)
    if body_text is None:
        return None
    return ResolvedArticle(
        canonical_url=url,
        original_url=url,
        final_url=final_url,
        title=title,
        subtitle=subtitle,
        source=config.source.source_name,
        author=author,
        published_at=published_at,
        body_text=body_text,
        trace=(config.source.slug,),
    )


def _select_main_article(soup: BeautifulSoup) -> Tag | None:
    candidates = soup.select("main article") or soup.find_all("article")
    if not candidates:
        return None
    return max(candidates, key=lambda node: len(node.get_text(" ", strip=True).split()))


def _clone_article(article: Tag) -> Tag:
    clone = BeautifulSoup(str(article), "lxml").find("article")
    assert clone is not None
    return clone


def _drop_noise_nodes(article: Tag) -> None:
    for selector in DROP_SELECTORS:
        for node in article.select(selector):
            node.decompose()


def _extract_title(article: Tag) -> str | None:
    heading = article.find("h1")
    if heading is None:
        return None
    return normalize_archive_text(heading.get_text(" ", strip=True)) or None


def _extract_meta_title(soup: BeautifulSoup, config: SourceParserConfig) -> str | None:
    raw_title = soup.title.get_text(" ", strip=True) if soup.title else None
    if not raw_title:
        tag = soup.find("meta", attrs={"property": "og:title"})
        if tag and tag.get("content"):
            raw_title = str(tag["content"]).strip()
    if not raw_title:
        return None
    suffixes = {
        "zeit": (" | DIE ZEIT",),
        "spiegel": (" - DER SPIEGEL",),
        "nytimes": (" - The New York Times",),
        "sueddeutsche": (" - Meinung - SZ.de", " - SZ.de"),
        "faz": (" | FAZ",),
    }[config.source.slug]
    for suffix in suffixes:
        if raw_title.endswith(suffix):
            raw_title = raw_title[: -len(suffix)]
            break
    return normalize_archive_text(raw_title) or None


def _extract_subtitle(article: Tag, title: str, config: SourceParserConfig) -> str | None:
    if config.source.slug == "zeit":
        heading = article.find("h1")
        if heading is not None and heading.parent is not None:
            for sibling in heading.parent.find_next_siblings():
                candidate = normalize_archive_text(sibling.get_text(" ", strip=True))
                if _looks_like_subtitle(candidate, title, config):
                    return candidate
    for node in article.find_all(("div", "p"), recursive=True):
        text = normalize_archive_text(node.get_text(" ", strip=True))
        if _looks_like_subtitle(text, title, config):
            return text
    return None


def _looks_like_subtitle(text: str, title: str, config: SourceParserConfig) -> bool:
    if not text or text == title or _contains_noise(text, config) or _looks_like_caption(text):
        return False
    lowered = text.lower()
    if any(
        marker in lowered
        for marker in ("von ", "by ", "kommentar von ", "interview:", "aktualisiert am")
    ):
        return False
    if text.endswith(("Uhr", "ET")):
        return False
    return len(text.split()) >= 10 and any(mark in text for mark in '.!?”“"')


def _extract_author(flat_text: str, config: SourceParserConfig) -> str | None:
    pattern = {
        "zeit": r"Interview:\s+(.+?)\s+Aus der",
        "spiegel": r"Von\s+(.+?)\s+\d{2}\.\d{2}\.\d{4}",
        "nytimes": r"By\s+(.+?)\s+Reporting from",
        "sueddeutsche": r"Kommentar von\s+(.+?)\s+\d{1,2}\.\s+[A-ZÄÖÜa-zäöü]+\s+\d{4}",
        "faz": r"Von\s+(.+?)\s+\d{2}\.\d{2}\.\d{4}",
    }[config.source.slug]
    match = re.search(pattern, flat_text, re.DOTALL)
    if match is None:
        return None
    author = " ".join(dict.fromkeys(normalize_archive_text(match.group(1)).splitlines()))
    return author.split(",", 1)[0].strip() if config.source.slug == "faz" else author


def _extract_markdown_body(
    article: Tag,
    title: str,
    subtitle: str | None,
    author: str | None,
    published_at: str | None,
    config: SourceParserConfig,
) -> str | None:
    skip_texts = {title, subtitle, author, published_at} - {None}
    parts: list[str] = []
    seen: set[str] = set()
    started = False
    zeit_ready = config.source.slug != "zeit"
    for node in article.find_all(BODY_TAGS):
        if any(isinstance(child, Tag) and child.name in BODY_TAGS for child in node.children):
            continue
        raw_text = normalize_archive_text(node.get_text(" ", strip=True))
        if not raw_text or raw_text in skip_texts:
            continue
        if (
            config.source.slug == "zeit"
            and node.name in HEADING_TAGS
            and "seite" in raw_text.lower()
        ):
            zeit_ready = True
            continue
        if not zeit_ready or _is_metadata_line(raw_text, author):
            continue
        if _contains_noise(raw_text, config) or _looks_like_caption(raw_text):
            continue
        if any(marker in raw_text.lower() for marker in config.stop_markers):
            break
        if not started and (node.name in HEADING_TAGS or not _looks_like_body_paragraph(raw_text)):
            continue
        started = True
        rendered = _render_markdown_block(node, raw_text)
        if rendered not in seen:
            seen.add(rendered)
            parts.append(rendered)
    return "\n\n".join(parts).strip() or None


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
    if any(marker in lowered for marker in ("foto:", "credit...", "/ ap", "/ dpa", "/ sf")):
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
