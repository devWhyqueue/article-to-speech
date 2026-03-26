from __future__ import annotations

from urllib.parse import urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

NOISE_MARKERS = (
    "zur merkliste hinzufügen",
    "artikel anhören",
    "weitere optionen zum teilen",
    "bild vergrößern",
    "foto:",
    "dieser artikel gehört zum angebot von spiegel+",
    "mehr zum thema",
    "debatte",
    "diskutieren sie hier",
    "startseite feedback",
    "diese zusammenfassung wurde",
    "fanden sie die zusammenfassung hilfreich",
    "diese audioversion wurde künstlich erzeugt",
    "die audioversion dieses artikels wurde künstlich erzeugt",
    "wir entwickeln dieses angebot stetig weiter",
    "newsletter",
    "ausgabe entdecken",
    "kommentieren",
    "1 kommentar",
    "exakt mein gedankengang",
)
DROP_SELECTORS = (
    "aside",
    "nav",
    "footer",
    "form",
    "button",
    "[id*='comment']",
    "[class*='comment']",
    "[aria-label*='Kommentar' i]",
    "[aria-label*='comments' i]",
    "[aria-label*='Mehr zum Thema' i]",
    "[aria-label*='Newsletter' i]",
    "[aria-label*='Seitennavigation' i]",
    "[aria-label*='Schlagwörter' i]",
    "[aria-label*='Navigationspfad' i]",
    "[href$='#comments']",
)
STOP_MARKERS = (
    "kommentar",
    "kommentieren",
    "jetzt teilen auf",
    "link kopieren",
    "schlagwörter",
    "navigationspfad",
)
SUBTITLE_SKIP_MARKERS = (
    "interview:",
    "aktualisiert am",
    "veröffentlicht am",
    "erschienen in",
    "artikel aus",
    "z+",
)


def contains_archive_noise(text: str) -> bool:
    """Return whether extracted text still contains archive-page noise markers."""
    lowered = text.lower()
    return any(marker in lowered for marker in NOISE_MARKERS)


def is_archive_url(url: str) -> bool:
    """Return whether the resolved URL points to an archive snapshot host."""
    return urlparse(url).netloc.lower() in {"archive.is", "archive.today", "archive.ph"}


def extract_archive_replay_text(
    soup: BeautifulSoup,
    *,
    normalize_text,
    extract_document_headline,
) -> str | None:
    """Extract the article body from archive replay pages."""
    modern = _extract_modern_article_text(
        soup,
        normalize_text=normalize_text,
        extract_document_headline=extract_document_headline,
    )
    return modern or _extract_fallback_text(soup, normalize_text=normalize_text)


def _extract_fallback_text(soup: BeautifulSoup, *, normalize_text) -> str | None:
    content = soup.select_one("#CONTENT")
    if content is None:
        return None
    articles = content.find_all("article")
    if not articles:
        return None
    article = max(
        articles, key=lambda item: len(normalize_text(item.get_text(" ", strip=True)).split())
    )
    best_container: Tag | None = None
    best_score = (0, 0)
    for container in article.find_all("div"):
        direct_children = container.find_all(recursive=False)
        if not direct_children:
            continue
        blocks = [
            normalize_text(child.get_text(" ", strip=True))
            for child in direct_children
            if _looks_like_body_block(normalize_text(child.get_text(" ", strip=True)))
        ]
        score = (len(blocks), sum(len(block.split()) for block in blocks))
        if score > best_score:
            best_container = container
            best_score = score
    if best_container is None or best_score[0] < 3:
        return None
    parts = [
        text
        for child in best_container.find_all(recursive=False)
        if _looks_like_body_block(text := normalize_text(child.get_text(" ", strip=True)))
    ]
    cleaned = normalize_text("\n\n".join(parts))
    return cleaned or None


def _extract_modern_article_text(
    soup: BeautifulSoup,
    *,
    normalize_text,
    extract_document_headline,
) -> str | None:
    article = soup.select_one("main article")
    if article is None:
        return None
    article = _clone_tag(article)
    for selector in DROP_SELECTORS:
        for node in article.select(selector):
            node.decompose()
    headline = extract_document_headline(article)
    subtitle = _extract_subtitle(article, headline, normalize_text=normalize_text)
    parts = [part for part in (headline, subtitle) if part]
    for child in article.find_all(recursive=False):
        if child.name in {"header", "figure"}:
            continue
        if _should_stop(normalize_text(child.get_text(" ", strip=True))):
            break
        parts.extend(_collect_body_blocks(child, normalize_text=normalize_text))
    cleaned = normalize_text("\n\n".join(_dedupe(parts)))
    return cleaned or None


def _clone_tag(tag: Tag) -> Tag:
    clone = BeautifulSoup(str(tag), "lxml").find(tag.name)
    assert clone is not None
    return clone


def _extract_subtitle(article: Tag, headline: str | None, *, normalize_text) -> str | None:
    for node in article.find_all(["p", "div"], recursive=True):
        if node.find(["h1", "h2", "h3", "p", "blockquote", "section", "article"], recursive=False):
            continue
        text = normalize_text(node.get_text(" ", strip=True))
        if not text or text == headline or contains_archive_noise(text):
            continue
        if _looks_like_subtitle(text):
            return text
    return None


def _looks_like_subtitle(text: str) -> bool:
    lowered = text.lower()
    return (
        len(text.split()) >= 10
        and not any(marker in lowered for marker in SUBTITLE_SKIP_MARKERS)
        and any(punctuation in text for punctuation in (".", "?", "!", ";", ":"))
    )


def _looks_like_body_block(text: str) -> bool:
    return (
        len(text.split()) >= 12
        and not contains_archive_noise(text)
        and any(punctuation in text for punctuation in (".", "?", "!", ";", ":"))
    )


def _looks_like_heading(text: str) -> bool:
    word_count = len(text.split())
    return (
        not contains_archive_noise(text)
        and 4 <= word_count <= 14
        and not any(punctuation in text for punctuation in (".", "?", "!", ";", ":"))
    )


def _collect_body_blocks(container: Tag, *, normalize_text) -> list[str]:
    blocks: list[str] = []
    for node in container.find_all(["h2", "p", "blockquote", "div"], recursive=True):
        if any(
            isinstance(child, Tag)
            and child.name in {"h2", "p", "blockquote", "div", "section", "article"}
            for child in node.children
        ):
            continue
        text = normalize_text(node.get_text(" ", strip=True))
        if not text:
            continue
        if _should_stop(text):
            break
        if _looks_like_heading(text) or _looks_like_body_block(text):
            blocks.append(text)
    return blocks


def _should_stop(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in STOP_MARKERS)


def _dedupe(parts: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for part in parts:
        if part in seen:
            continue
        seen.add(part)
        deduped.append(part)
    return deduped
