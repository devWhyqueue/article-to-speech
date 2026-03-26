from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

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


def _normalize_date(raw_value: str) -> str:
    cleaned = raw_value.strip()
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
    return date_parser.parse(cleaned, fuzzy=True).date().isoformat()
