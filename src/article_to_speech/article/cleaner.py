from __future__ import annotations

import re

from article_to_speech.article.chunking import build_chunk_texts
from article_to_speech.core.models import NarrationChunk, ResolvedArticle

WHITESPACE_PATTERN = re.compile(r"[ \t]+")
MULTI_NEWLINE_PATTERN = re.compile(r"\n{3,}")
SHORT_LABEL_PATTERN = re.compile(r"^[A-Z0-9][A-Za-z0-9'’&:/ -]{0,48}$")
# Bare data-point lines from scraped chart/graph widgets (e.g. "12.421", one per
# line). Real prose never puts a lone number on its own line; dropping these
# also removes long unpunctuated digit runs that Google TTS rejects outright.
BARE_NUMBER_PATTERN = re.compile(r"^[\d.,]+\*?$")
MARKDOWN_HEADING_PATTERN = re.compile(r"^#{1,6}\s+")
MARKDOWN_QUOTE_PATTERN = re.compile(r"^>\s*")
BOILERPLATE_PREFIXES = (
    "advertisement",
    "read more",
    "related:",
    "share full article",
    "share article",
    "editors’ picks",
    "editors' picks",
    "our coverage of",
    "follow live updates",
)
TRAILING_SECTION_PREFIXES = (
    "see more on:",
    "related content",
    "more in ",
    "trending in the times",
    "editors’ picks",
    "editors' picks",
)
HEADING_SENTINEL = "\u0000heading\u0000"


class NarrationFormatter:
    max_tts_input_bytes = 4_500
    # ponytail: Google TTS rejects any single sentence over some undocumented byte
    # length ("sentences that are too long"). Confirmed in production: a 721-byte
    # unpunctuated run (a chart's numeric data points glued together with no real
    # words) got rejected, while normal ~200-340-byte prose sentences did not. 400
    # keeps clear margin below the known-bad value; tighten further if it recurs.
    max_sentence_bytes = 400

    def clean_article_text(self, article: ResolvedArticle) -> str:
        """Convert markdown article content into narration-friendly plain text."""
        parts = self._intro_parts(article)
        body = self._clean_body(article, parts)
        if body:
            parts.append(body)
        return "\n\n".join(parts)

    def build_chunks(self, article: ResolvedArticle) -> list[NarrationChunk]:
        """Build narration chunks sized for Google Cloud Text-to-Speech requests."""
        intro_parts = self._intro_parts(article)
        intro_text = "\n\n".join(intro_parts).strip()
        body = self._clean_body(article, intro_parts)
        chunk_texts = build_chunk_texts(
            intro_text,
            body,
            max_tts_input_bytes=self.max_tts_input_bytes,
            max_sentence_bytes=self.max_sentence_bytes,
        )
        return [NarrationChunk(text=chunk_text) for chunk_text in chunk_texts]

    def _clean_body(self, article: ResolvedArticle, intro_parts: list[str]) -> str:
        body = MULTI_NEWLINE_PATTERN.sub("\n\n", _clean_markdown_body(article.body_text)).strip()
        body = _strip_leading_intro_duplicates(
            _trim_trailing_noise_sections(_trim_leading_noise(body)), intro_parts
        )
        return body.replace(HEADING_SENTINEL, "")

    def _intro_parts(self, article: ResolvedArticle) -> list[str]:
        return [article.title, article.subtitle] if article.subtitle else [article.title]


def _clean_markdown_body(body_text: str) -> str:
    lines: list[str] = []
    for raw_line in body_text.splitlines():
        stripped = WHITESPACE_PATTERN.sub(" ", raw_line).strip()
        if not stripped:
            lines.append("")
            continue
        was_heading = MARKDOWN_HEADING_PATTERN.match(stripped) is not None
        stripped = MARKDOWN_HEADING_PATTERN.sub("", stripped)
        stripped = MARKDOWN_QUOTE_PATTERN.sub("", stripped)
        if was_heading:
            lines.append(f"{HEADING_SENTINEL}{stripped}")
            continue
        lowered = stripped.lower()
        if (
            lowered.startswith(BOILERPLATE_PREFIXES)
            or _looks_like_chrome_label(stripped)
            or BARE_NUMBER_PATTERN.match(stripped) is not None
        ):
            continue
        lines.append(stripped)
    return "\n".join(lines)


def _looks_like_chrome_label(text: str) -> bool:
    return bool(
        SHORT_LABEL_PATTERN.match(text)
        and not any(character in text for character in ".!?")
        and len(text.split()) <= 5
    )


def _trim_leading_noise(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    for index, line in enumerate(lines):
        if (
            not _looks_like_sentence(line)
            and index + 1 < len(lines)
            and _looks_like_sentence(lines[index + 1])
            and not _looks_like_chrome_label(line)
        ):
            return "\n\n".join(lines[index:])
        if _looks_like_sentence(line):
            return "\n\n".join(lines[index:])
    return "\n\n".join(lines)


def _trim_trailing_noise_sections(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    for index, line in enumerate(lines):
        lowered = line.lower()
        if any(lowered.startswith(prefix) for prefix in TRAILING_SECTION_PREFIXES):
            return "\n".join(lines[:index]).strip()
    return "\n".join(lines).strip()


def _strip_leading_intro_duplicates(text: str, intro_parts: list[str]) -> str:
    if not text or not intro_parts:
        return text
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    intro_sequence = [part.strip() for part in intro_parts if part and part.strip()]
    if not paragraphs or not intro_sequence:
        return text
    while paragraphs[: len(intro_sequence)] == intro_sequence:
        paragraphs = paragraphs[len(intro_sequence) :]
    intro_set = set(intro_sequence)
    while paragraphs and paragraphs[0] in intro_set:
        paragraphs = paragraphs[1:]
    return "\n\n".join(paragraphs)


def _looks_like_sentence(text: str) -> bool:
    if text.endswith((".", "!", "?")):
        return True
    words = text.split()
    return len(words) >= 10 and any(character.islower() for character in text)
