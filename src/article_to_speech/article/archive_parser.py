from __future__ import annotations

import re

from bs4 import BeautifulSoup
from bs4.element import Tag

from article_to_speech.article import (
    _clone_article,
    _drop_nested_articles,
    _drop_spiegel_ad_sections,
    _is_spiegel_embedded_media_block,
    _normalize_archive_text,
    _select_main_article,
)
from article_to_speech.article.parser_config import (
    BODY_TAGS,
    DROP_SELECTORS,
    HEADING_TAGS,
    _contains_noise,
    _contains_zeit_page_heading,
    _extract_spiegel_subtitle_candidate,
    _is_metadata_line,
    _is_stop_block,
    _looks_like_body_paragraph,
    _looks_like_caption,
    _render_markdown_block,
    extract_published_at,
)
from article_to_speech.article.source_detection import detect_supported_source
from article_to_speech.article_helpers import (
    CONFIG_BY_SLUG,
    SourceParserConfig,
    _extract_body_lead,
    _looks_like_subtitle,
)
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
    _drop_nested_articles(article)
    _drop_noise_nodes(article, config)
    return _build_article(url, final_url, soup, article, config)


def _build_article(
    url: str,
    final_url: str,
    soup: BeautifulSoup,
    article: Tag,
    config: SourceParserConfig,
) -> ResolvedArticle | None:
    title = _extract_title(article, config) or _extract_meta_title(soup, config)
    if title is None:
        return None
    flat_text = _normalize_archive_text(article.get_text("\n", strip=True))
    subtitle = _extract_subtitle(article, title, config)
    author = _extract_author(article, flat_text, config)
    published_at = _extract_published_at(article, flat_text, config)
    body_text = _extract_markdown_body(article, title, subtitle, author, published_at, config)
    if config.source.slug == "spiegel" and subtitle and subtitle.startswith("SPIEGEL:"):
        if corrected_subtitle := _extract_body_lead(body_text):
            subtitle = corrected_subtitle
            body_text = _extract_markdown_body(
                article, title, subtitle, author, published_at, config
            )
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


def _drop_noise_nodes(article: Tag, config: SourceParserConfig) -> None:
    for selector in DROP_SELECTORS:
        for node in article.select(selector):
            node.decompose()
    if config.source.slug == "spiegel":
        _drop_spiegel_ad_sections(article)


def _extract_title(article: Tag, config: SourceParserConfig) -> str | None:
    heading = article.find("h1")
    title = _normalize_archive_text(heading.get_text(" ", strip=True)) or None if heading else None
    return None if title == config.source.source_name else title


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
        "spektrum": (" - Spektrum der Wissenschaft",),
    }[config.source.slug]
    for suffix in suffixes:
        if raw_title.endswith(suffix):
            raw_title = raw_title[: -len(suffix)]
            break
    return _normalize_archive_text(raw_title) or None


def _extract_subtitle(article: Tag, title: str, config: SourceParserConfig) -> str | None:
    if config.source.slug == "spiegel":
        subtitle = _extract_spiegel_subtitle_candidate(article, title, config)
        if subtitle is not None:
            return subtitle
    if config.source.slug == "zeit":
        heading = article.find("h1")
        if heading is not None and heading.parent is not None:
            for sibling in heading.parent.find_next_siblings():
                candidate = _normalize_archive_text(sibling.get_text(" ", strip=True))
                if _looks_like_subtitle(candidate, title, config):
                    return candidate
    for node in article.find_all(("div", "p"), recursive=True):
        text = _normalize_archive_text(node.get_text(" ", strip=True))
        if _looks_like_subtitle(text, title, config):
            return text
    return None


def _extract_author(article: Tag, flat_text: str, config: SourceParserConfig) -> str | None:
    if config.source.slug == "spiegel":
        if author := _extract_spiegel_author(article):
            return author
    pattern = {
        "zeit": r"Interview:\s+(.+?)\s+Aus der",
        "spiegel": r"Von\s+(.+?)\s+\d{2}\.\d{2}\.\d{4}",
        "nytimes": r"By\s+(.+?)\s+Reporting from",
        "sueddeutsche": r"Kommentar von\s+(.+?)\s+\d{1,2}\.\s+[A-ZÄÖÜa-zäöü]+\s+\d{4}",
        "faz": r"Von\s+(.+?)\s+\d{2}\.\d{2}\.\d{4}",
        "spektrum": r"(?mi)^von\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß-]+(?:\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß-]+){0,3})$",
    }[config.source.slug]
    match = re.search(pattern, flat_text, re.DOTALL)
    if match is None:
        return None
    author = " ".join(dict.fromkeys(_normalize_archive_text(match.group(1)).splitlines()))
    return author.split(",", 1)[0].strip() if config.source.slug == "faz" else author


def _extract_spiegel_author(article: Tag) -> str | None:
    marker = article.find(string=re.compile(r"^\s*Ein Interview von\s*$"))
    link = marker.parent.find("a") if marker and marker.parent is not None else None
    return _normalize_archive_text(link.get_text(" ", strip=True)) or None if link else None


def _extract_published_at(article: Tag, flat_text: str, config: SourceParserConfig) -> str | None:
    if config.source.slug == "spiegel":
        published_time = article.find("time")
        if published_time is not None:
            published_at = extract_published_at(
                _normalize_archive_text(published_time.get_text(" ", strip=True))
            )
            if published_at is not None:
                return published_at
    return extract_published_at(flat_text)


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
    spiegel_paused = False
    spektrum_skip_caption_followup = False
    zeit_ready = config.source.slug != "zeit" or not _contains_zeit_page_heading(article)
    for node in article.find_all(BODY_TAGS):
        if any(isinstance(child, Tag) and child.name in BODY_TAGS for child in node.children):
            continue
        raw_text = _normalize_archive_text(node.get_text(" ", strip=True))
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
        if spiegel_paused:
            if not re.match(r"^[A-ZÄÖÜ][A-Za-zÄÖÜäöüß-]+:", raw_text):
                continue
            spiegel_paused = False
        if config.source.slug == "spiegel" and _is_spiegel_embedded_media_block(raw_text):
            spiegel_paused = True
            continue
        if config.source.slug == "spektrum" and spektrum_skip_caption_followup:
            spektrum_skip_caption_followup = False
            if 6 <= len(raw_text.split()) <= 26 and raw_text.endswith("."):
                continue
        if _contains_noise(raw_text, config) or _looks_like_caption(raw_text):
            if config.source.slug == "spektrum" and _looks_like_caption(raw_text):
                spektrum_skip_caption_followup = True
            continue
        if _is_stop_block(node, raw_text, config):
            if config.source.slug == "spiegel":
                spiegel_paused = True
                continue
            break
        spektrum_skip_caption_followup = False
        if not started and (node.name in HEADING_TAGS or not _looks_like_body_paragraph(raw_text)):
            continue
        started = True
        rendered = _render_markdown_block(node, raw_text)
        if rendered not in seen:
            seen.add(rendered)
            parts.append(rendered)
    return "\n\n".join(parts).strip() or None
