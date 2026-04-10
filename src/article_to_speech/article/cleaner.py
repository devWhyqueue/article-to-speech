from __future__ import annotations

import re

from article_to_speech.core.models import NarrationChunk, ResolvedArticle

WHITESPACE_PATTERN = re.compile(r"[ \t]+")
MULTI_NEWLINE_PATTERN = re.compile(r"\n{3,}")
SHORT_LABEL_PATTERN = re.compile(r"^[A-Z0-9][A-Za-z0-9'’&:/ -]{0,48}$")
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

    def clean_article_text(self, article: ResolvedArticle) -> str:
        """Convert markdown article content into narration-friendly plain text."""
        parts = self._intro_parts(article)
        body = self._clean_body(article, parts)
        if body:
            parts.append(body)
        return "\n\n".join(parts)

    def build_chunks(self, article: ResolvedArticle) -> list[NarrationChunk]:
        """Build narration chunks sized for Google Cloud Text-to-Speech requests."""
        cleaned = self.clean_article_text(article)
        if self._fits_budget(cleaned):
            return [NarrationChunk(text=cleaned)]
        return self._build_chunked_chunks(article)

    def _build_chunked_chunks(self, article: ResolvedArticle) -> list[NarrationChunk]:
        intro_parts = self._intro_parts(article)
        intro_text = "\n\n".join(intro_parts).strip()
        body = self._clean_body(article, intro_parts)
        body_segments = self._split_body_segments(body, self.max_tts_input_bytes)
        chunk_texts = self._assemble_chunk_texts(
            intro_text, body_segments, self.max_tts_input_bytes
        )
        return [NarrationChunk(text=chunk_text) for chunk_text in chunk_texts]

    def _assemble_chunk_texts(
        self,
        intro_text: str,
        body_segments: list[str],
        text_budget: int,
    ) -> list[str]:
        chunks: list[str] = []
        current = intro_text
        remaining_segments = list(body_segments)
        if current and remaining_segments:
            first_candidate = f"{current}\n\n{remaining_segments[0]}"
            if not self._fits_budget(first_candidate, text_budget):
                available = text_budget - _utf8_len(current) - _utf8_len("\n\n")
                if available > 0:
                    split_segments = self._split_text_to_fit(remaining_segments.pop(0), available)
                    current = f"{current}\n\n{split_segments[0]}".strip()
                    remaining_segments = split_segments[1:] + remaining_segments
        for segment in remaining_segments:
            candidate = f"{current}\n\n{segment}".strip() if current else segment
            if candidate and self._fits_budget(candidate, text_budget):
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = segment
        if current:
            chunks.append(current)
        return chunks

    def _split_body_segments(self, body: str, text_budget: int) -> list[str]:
        if not body:
            return []
        segments: list[str] = []
        for paragraph in body.split("\n\n"):
            if self._fits_budget(paragraph, text_budget):
                segments.append(paragraph)
                continue
            segments.extend(self._split_text_to_fit(paragraph, text_budget))
        return segments

    def _split_text_to_fit(self, text: str, text_budget: int) -> list[str]:
        if self._fits_budget(text, text_budget):
            return [text]
        sentences = _split_into_sentences(text)
        if len(sentences) == 1:
            return self._hard_split(text, text_budget)
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            sentence_parts = (
                [sentence]
                if self._fits_budget(sentence, text_budget)
                else self._hard_split(sentence, text_budget)
            )
            for part in sentence_parts:
                candidate = f"{current} {part}".strip() if current else part
                if candidate and self._fits_budget(candidate, text_budget):
                    current = candidate
                    continue
                if current:
                    chunks.append(current)
                current = part
        if current:
            chunks.append(current)
        return chunks

    def _hard_split(self, text: str, text_budget: int) -> list[str]:
        remaining = text.strip()
        chunks: list[str] = []
        while remaining:
            if self._fits_budget(remaining, text_budget):
                chunks.append(remaining)
                break
            split_at = _split_index_for_budget(remaining, text_budget)
            if split_at <= 0:
                split_at = max(1, _hard_split_index_for_budget(remaining, text_budget))
            chunks.append(remaining[:split_at].strip())
            remaining = remaining[split_at:].strip()
        return chunks

    def _clean_body(self, article: ResolvedArticle, intro_parts: list[str]) -> str:
        body = MULTI_NEWLINE_PATTERN.sub("\n\n", _clean_markdown_body(article.body_text)).strip()
        body = _strip_leading_intro_duplicates(
            _trim_trailing_noise_sections(_trim_leading_noise(body)), intro_parts
        )
        return body.replace(HEADING_SENTINEL, "")

    def _intro_parts(self, article: ResolvedArticle) -> list[str]:
        return [article.title, article.subtitle] if article.subtitle else [article.title]

    def _fits_budget(self, text: str, text_budget: int | None = None) -> bool:
        budget = self.max_tts_input_bytes if text_budget is None else text_budget
        return _utf8_len(text) <= budget


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
        if lowered.startswith(BOILERPLATE_PREFIXES) or _looks_like_chrome_label(stripped):
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


def _split_into_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [part.strip() for part in parts if part.strip()]


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
