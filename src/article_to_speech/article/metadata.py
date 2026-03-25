from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from dateutil import parser as date_parser


def extract_metadata(soup: BeautifulSoup, final_url: str) -> dict[str, str | None]:
    """Extract article metadata from HTML meta tags and JSON-LD."""
    title = _meta_content(soup, "og:title") or _meta_content(soup, "twitter:title")
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()
    source = _source_name(soup, final_url)
    author = _author_name(soup)
    published = _published_value(soup)
    return {
        "title": title,
        "source": source,
        "author": author,
        "published_at": published,
    }


def _source_name(soup: BeautifulSoup, final_url: str) -> str:
    return (
        _meta_content(soup, "og:site_name")
        or _meta_name_content(soup, "application-name")
        or urlparse(final_url).netloc
    )


def _author_name(soup: BeautifulSoup) -> str | None:
    return (
        _meta_name_content(soup, "author")
        or _meta_content(soup, "article:author")
        or _extract_author_from_ld_json(soup)
    )


def _published_value(soup: BeautifulSoup) -> str | None:
    published = (
        _meta_content(soup, "article:published_time")
        or _meta_name_content(soup, "date")
        or _extract_date_from_ld_json(soup)
    )
    if not published:
        return None
    try:
        return date_parser.parse(published).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return published


def _meta_content(soup: BeautifulSoup, property_name: str) -> str | None:
    tag = soup.find("meta", attrs={"property": property_name})
    if tag and tag.get("content"):
        return str(tag["content"]).strip()
    return None


def _meta_name_content(soup: BeautifulSoup, name: str) -> str | None:
    tag = soup.find("meta", attrs={"name": name})
    if tag and tag.get("content"):
        return str(tag["content"]).strip()
    return None


def _extract_author_from_ld_json(soup: BeautifulSoup) -> str | None:
    for block in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = block.string or block.text
        if not text:
            continue
        for payload in _load_possible_json(text):
            for article_object in _iter_article_objects(payload):
                author = article_object.get("author")
                if isinstance(author, dict) and isinstance(author.get("name"), str):
                    return author["name"].strip()
                if isinstance(author, list):
                    names = [
                        item.get("name", "").strip() for item in author if isinstance(item, dict)
                    ]
                    names = [name for name in names if name]
                    if names:
                        return ", ".join(names)
    return None


def _extract_date_from_ld_json(soup: BeautifulSoup) -> str | None:
    for block in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = block.string or block.text
        if not text:
            continue
        for payload in _load_possible_json(text):
            for article_object in _iter_article_objects(payload):
                date_value = article_object.get("datePublished")
                if isinstance(date_value, str) and date_value.strip():
                    return date_value.strip()
    return None


def _load_possible_json(text: str) -> list[dict[str, Any] | list[Any]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        return payload
    return [payload]


def _iter_article_objects(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload_type = payload.get("@type")
        if payload_type in {"NewsArticle", "Article", "ReportageNewsArticle"}:
            return [payload]
        if isinstance(payload.get("@graph"), list):
            objects: list[dict[str, Any]] = []
            for item in payload["@graph"]:
                objects.extend(_iter_graph_items(item))
            return objects
    return []


def _iter_graph_items(item: Any) -> Iterable[dict[str, Any]]:
    if isinstance(item, dict):
        return _iter_article_objects(item)
    return []
