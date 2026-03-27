from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from bs4.element import Tag
from dateutil import parser as date_parser

from article_to_speech.article.source_detection import SupportedSource

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


@dataclass(frozen=True, slots=True)
class SourceParserConfig:
    source: SupportedSource
    noise_markers: tuple[str, ...]
    stop_markers: tuple[str, ...]


CONFIG_BY_SLUG: Final[dict[str, SourceParserConfig]] = {
    "zeit": SourceParserConfig(
        source=SupportedSource("zeit", "DIE ZEIT", ("zeit.de",)),
        noise_markers=(
            "artikel verschenken",
            "aus der zeit nr.",
            "artikel aus die zeit",
            "veröffentlicht am",
            "erschienen in",
            "gedruckte version anzeigen",
            "artikelzusammenfassung",
            "diese zusammenfassung wurde",
            "fanden sie die zusammenfassung hilfreich",
            "die audioversion dieses artikels wurde künstlich erzeugt",
            "wir entwickeln dieses angebot stetig weiter",
            "newsletter",
            "kommentare",
            "feedback senden",
            "© gene glover",
        ),
        stop_markers=("1 kommentar", "kommentare", "exakt mein gedankengang"),
    ),
    "spiegel": SourceParserConfig(
        source=SupportedSource("spiegel", "DER SPIEGEL", ("spiegel.de",)),
        noise_markers=(
            "bild vergrößern",
            "zur merkliste hinzufügen",
            "artikel anhören",
            "weitere optionen zum teilen",
            "dieser artikel gehört zum angebot von spiegel+",
            "foto:",
            "messenger whatsapp",
        ),
        stop_markers=("mehr zum thema", "startseite", "kommentare"),
    ),
    "nytimes": SourceParserConfig(
        source=SupportedSource("nytimes", "The New York Times", ("nytimes.com",)),
        noise_markers=(
            "advertisement",
            "skip advertisement",
            "share full article",
            "supported by",
            "listen ·",
            "credit...",
            "static01.nyt.com is blocked",
        ),
        stop_markers=("related coverage", "more on", "comments"),
    ),
    "sueddeutsche": SourceParserConfig(
        source=SupportedSource("sueddeutsche", "SZ.de", ("sueddeutsche.de", "sz.de")),
        noise_markers=(
            "home meinung",
            "artikel anhören",
            "anhören",
            "merken",
            "teilen",
            "feedback",
            "drucken",
            "kommentare",
            "lesezeit:",
        ),
        stop_markers=("kuba :", "mehr zum thema", "kommentare"),
    ),
    "faz": SourceParserConfig(
        source=SupportedSource("faz", "FAZ", ("faz.net",)),
        noise_markers=(
            "anhören",
            "merken",
            "teilen",
            "verschenken",
            "drucken",
            "zur app",
            "lesezeit:",
        ),
        stop_markers=("mehr zum thema", "kommentare"),
    ),
}


def extract_published_at(flat_text: str) -> str | None:
    """Return the normalized publication date from a flattened article text blob."""
    patterns = (
        r"\b\d{1,2}\.\d{1,2}\.\d{4}, \d{2}[:.]\d{2}\b",
        r"\b\d{1,2}\.\s+[A-ZÄÖÜa-zäöü]+\s+\d{4}, \d{1,2}:\d{2}\s+Uhr\b",
        r"\b[A-Z][a-z]+\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}\s+[ap]\.m\. ET\b",
    )
    for pattern in patterns:
        match = re.search(pattern, flat_text)
        if match is not None:
            return _normalize_date(match.group(0))
    return None


def normalize_archive_text(text: str) -> str:
    """Normalize archive snapshot text into stable, newline-preserving plain text."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.replace("\r", "\n").splitlines()]
    cleaned = "\n".join(line for line in lines if line).strip()
    cleaned = re.sub(r"\s+([:;,.!?])", r"\1", cleaned)
    cleaned = re.sub(r'([„“"»])\s+', r"\1", cleaned)
    return cleaned.replace('"“', "“").replace('"”', "”")


def _contains_zeit_page_heading(article: Tag) -> bool:
    return any(
        node.name in HEADING_TAGS
        and "seite" in normalize_archive_text(node.get_text(" ", strip=True)).lower()
        for node in article.find_all(HEADING_TAGS)
    )


def _is_stop_block(node: Tag, text: str, config: SourceParserConfig) -> bool:
    lowered = text.lower()
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
    cleaned = raw_value.strip()
    dayfirst = bool(re.match(r"\d{1,2}\.\d{1,2}\.\d{4}", cleaned))
    for german, english in {
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
    }.items():
        cleaned = re.sub(german, english, cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("Uhr", "").replace(" ET", "").strip()
    cleaned = re.sub(r",\s*(\d{1,2})\.(\d{2})$", r", \1:\2", cleaned)
    return date_parser.parse(cleaned, fuzzy=True, dayfirst=dayfirst).date().isoformat()
