"""Article resolution, extraction, and narration cleanup."""

from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup
from bs4.element import Tag

_SPIEGEL_AD_MARKERS = (
    "bei amazon bestellen",
    "bei thalia bestellen",
    "bei genialokal bestellen",
    "bei hugendubel bestellen",
    "preisabfragezeitpunkt",
    "produktbesprechungen erfolgen",
)
_SPIEGEL_EMBEDDED_MEDIA_MARKERS = (
    "tastaturkürzel",
    "spielen/pause",
    "shortcuts open/close",
    "weitere videos",
    "als nächstes",
    "0 seconds of",
    "volume 90%",
)
_GERMAN_MONTH_NAMES = {
    "januar": "January",
    "februar": "February",
    "märz": "March",
    "april": "April",
    "mai": "May",
    "juni": "June",
    "juli": "July",
    "august": "August",
    "september": "September",
    "oktober": "October",
    "november": "November",
    "dezember": "December",
}
_DATE_FORMATS = ("%d.%m.%Y, %H:%M", "%d.%m.%Y", "%d. %B %Y, %H:%M", "%B %d, %Y, %I:%M %p")


def _normalize_archive_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.replace("\r", "\n").splitlines()]
    cleaned = "\n".join(line for line in lines if line).strip()
    cleaned = re.sub(r"\s+([:;,.!?])", r"\1", cleaned)
    cleaned = re.sub(r'([„“"»])\s+', r"\1", cleaned)
    return cleaned.replace('"“', "“").replace('"”', "”")


def _select_main_article(soup: BeautifulSoup) -> Tag | None:
    candidates = soup.select("main article") or soup.find_all("article")
    return (
        max(candidates, key=lambda node: len(node.get_text(" ", strip=True).split()))
        if candidates
        else None
    )


def _clone_article(article: Tag) -> Tag:
    clone = BeautifulSoup(str(article), "lxml").find("article")
    assert clone is not None
    return clone


def _drop_nested_articles(article: Tag) -> None:
    for nested_article in article.find_all("article"):
        nested_article.decompose()


def _drop_spiegel_ad_sections(article: Tag) -> None:
    for node in article.find_all(("div", "section")):
        text = _normalize_archive_text(node.get_text(" ", strip=True)).lower()
        if len(text) > 1_500 or "anzeige" not in text:
            continue
        if any(marker in text for marker in _SPIEGEL_AD_MARKERS):
            node.decompose()


def _is_spiegel_embedded_media_block(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _SPIEGEL_EMBEDDED_MEDIA_MARKERS)


def _looks_like_spiegel_paywall(article: Tag, body_text: str | None) -> bool:
    article_text = _normalize_archive_text(article.get_text("\n", strip=True)).lower()
    paywall_markers = (
        "spiegel+",
        "4 wochen für 1 euro",
        "jetzt anmelden",
        "bereits abonnent",
        "als abonnent:in können sie diesen monat noch",
        "verschenkte artikel sind ohne abonnement lesbar",
        "mehr perspektiven, mehr verstehen",
        "inklusive digitaler ausgabe des wöchentlichen magazins",
    )
    marker_hits = sum(marker in article_text for marker in paywall_markers)
    if marker_hits < 3:
        return False
    if body_text is None:
        return True
    body_lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    prose_lines = [
        line
        for line in body_lines
        if not line.startswith("## ")
        and len(line.split()) >= 12
        and any(mark in line for mark in (".", "?", "!", "”", '"'))
    ]
    return len(prose_lines) < 2


def _normalize_publication_date(raw_value: str) -> str:
    cleaned = re.sub(r"\s+", " ", raw_value).strip()
    for german, english in _GERMAN_MONTH_NAMES.items():
        cleaned = re.sub(german, english, cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("Uhr", "").replace(" ET", "").strip()
    cleaned = cleaned.replace("a.m.", "AM").replace("p.m.", "PM")
    cleaned = re.sub(r",\s*(\d{1,2})\.(\d{2})$", r", \1:\2", cleaned)
    for date_format in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, date_format).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Unsupported publication date format: {raw_value}")
