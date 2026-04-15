from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from article_to_speech.article.source_detection import SupportedSource


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
        stop_markers=("anzeige", "mehr zum thema", "startseite", "kommentare"),
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
    "spektrum": SourceParserConfig(
        source=SupportedSource("spektrum", "Spektrum.de", ("spektrum.de",)),
        noise_markers=(
            "direkt zum inhalt",
            "spektrum.de logo",
            "lesedauer",
            "drucken",
            "teilen",
            "jetzt testen",
            "sie haben bereits ein abo",
            "bitte erlauben sie javascript",
        ),
        stop_markers=(
            "das könnte sie auch interessieren",
            "diesen artikel empfehlen",
            "weiterlesen mit »spektrum +«",
            "artikel zum thema",
            "themenkanäle",
            "sponsoredpartnerinhalte",
            "schreiben sie uns",
        ),
    ),
}


def _extract_body_lead(body_text: str | None) -> str | None:
    return body_text.partition("\n\n")[0] or None if body_text else None


def _contains_noise(text: str, config: SourceParserConfig) -> bool:
    return any(marker in text.lower() for marker in config.noise_markers)


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


def _looks_like_subtitle(text: str, title: str, config: SourceParserConfig) -> bool:
    if not text or text == title or _contains_noise(text, config) or _looks_like_caption(text):
        return False
    if any(
        line.lower().startswith(marker)
        for line in text.splitlines()
        for marker in ("von ", "by ", "kommentar von ", "interview:", "aktualisiert am")
    ):
        return False
    if text.endswith(("Uhr", "ET")):
        return False
    return len(text.split()) >= 10 and any(mark in text for mark in '.!?”“"')


def _utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _split_index_for_budget(text: str, text_budget: int) -> int:
    best_index = -1
    for index, character in enumerate(text):
        if _utf8_len(text[: index + 1]) > text_budget:
            break
        if character == " ":
            best_index = index
    return best_index


def _hard_split_index_for_budget(text: str, text_budget: int) -> int:
    for index in range(1, len(text) + 1):
        if _utf8_len(text[:index]) > text_budget:
            return index - 1
    return len(text)
