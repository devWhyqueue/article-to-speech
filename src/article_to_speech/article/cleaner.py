from __future__ import annotations

import re

from article_to_speech.core.models import NarrationRequest, ResolvedArticle

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
HEADING_SENTINEL = "\u0000heading\u0000"


class NarrationFormatter:
    max_chatgpt_message_chars = 5_000
    max_chunk_part_digits = 3

    def clean_article_text(self, article: ResolvedArticle) -> str:
        """Convert markdown article content into narration-friendly plain text."""
        body = self._clean_body(article)
        parts = self._intro_parts(article)
        if body:
            parts.append(body)
        return "\n\n".join(parts)

    def build_requests(self, article: ResolvedArticle) -> list[NarrationRequest]:
        """Build the ChatGPT narration request from the cleaned article body."""
        cleaned = self.clean_article_text(article)
        if len(cleaned) <= self._single_text_budget():
            return [NarrationRequest(article=article, prompt_text=self._single_prompt(cleaned))]
        return self._build_chunked_requests(article)

    def _build_chunked_requests(self, article: ResolvedArticle) -> list[NarrationRequest]:
        intro_text = "\n\n".join(self._intro_parts(article)).strip()
        body = self._clean_body(article)
        body_segments = self._split_body_segments(body, self._chunk_text_budget())
        chunk_texts = self._assemble_chunk_texts(
            intro_text, body_segments, self._chunk_text_budget()
        )
        part_count = len(chunk_texts)
        return [
            NarrationRequest(
                article=article,
                prompt_text=self._chunk_prompt(chunk_text, part_number, part_count),
            )
            for part_number, chunk_text in enumerate(chunk_texts, start=1)
        ]

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
            if len(first_candidate) > text_budget:
                available = text_budget - len(current) - 2
                if available > 0:
                    split_segments = self._split_text_to_fit(remaining_segments.pop(0), available)
                    current = f"{current}\n\n{split_segments[0]}".strip()
                    remaining_segments = split_segments[1:] + remaining_segments
        for segment in remaining_segments:
            candidate = f"{current}\n\n{segment}".strip() if current else segment
            if candidate and len(candidate) <= text_budget:
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
            if len(paragraph) <= text_budget:
                segments.append(paragraph)
                continue
            segments.extend(self._split_text_to_fit(paragraph, text_budget))
        return segments

    def _split_text_to_fit(self, text: str, text_budget: int) -> list[str]:
        if len(text) <= text_budget:
            return [text]
        sentences = _split_into_sentences(text)
        if len(sentences) == 1:
            return self._hard_split(text, text_budget)
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            sentence_parts = (
                [sentence]
                if len(sentence) <= text_budget
                else self._hard_split(sentence, text_budget)
            )
            for part in sentence_parts:
                candidate = f"{current} {part}".strip() if current else part
                if candidate and len(candidate) <= text_budget:
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
            if len(remaining) <= text_budget:
                chunks.append(remaining)
                break
            split_at = remaining.rfind(" ", 0, text_budget + 1)
            if split_at <= 0:
                split_at = text_budget
            chunks.append(remaining[:split_at].strip())
            remaining = remaining[split_at:].strip()
        return chunks

    def _clean_body(self, article: ResolvedArticle) -> str:
        body = MULTI_NEWLINE_PATTERN.sub("\n\n", _clean_markdown_body(article.body_text)).strip()
        body = _trim_leading_noise(body)
        return body.replace(HEADING_SENTINEL, "")

    def _intro_parts(self, article: ResolvedArticle) -> list[str]:
        parts = [article.title]
        if article.subtitle:
            parts.append(article.subtitle)
        return parts

    def _single_prompt(self, text: str) -> str:
        return (
            "The user provided article text for a private accessibility read-aloud. "
            "Keep the title first, subtitle second when present, then the main text. "
            "Preserve wording, drop obvious noise, and do not read markdown punctuation literally.\n\n"
            f"<text>\n{text}\n</text>"
        )

    def _chunk_prompt(self, text: str, part_number: int, part_count: int) -> str:
        return (
            "The user provided article text for a private accessibility read-aloud. "
            f"This is Part {part_number} of {part_count}. "
            "Output the full cleaned text of this part as a direct continuation of the article. "
            "Preserve the wording, remove obvious noise, keep paragraph breaks, and return only "
            "the cleaned passage.\n\n"
            f"{text}"
        )

    def _single_text_budget(self) -> int:
        return self.max_chatgpt_message_chars - len(self._single_prompt(""))

    def _chunk_text_budget(self) -> int:
        max_part_number = int("9" * self.max_chunk_part_digits)
        return self.max_chatgpt_message_chars - len(
            self._chunk_prompt("", max_part_number, max_part_number)
        )


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
    if not SHORT_LABEL_PATTERN.match(text):
        return False
    if any(character in text for character in ".!?"):
        return False
    return len(text.split()) <= 5


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


def _looks_like_sentence(text: str) -> bool:
    if text.endswith((".", "!", "?")):
        return True
    words = text.split()
    return len(words) >= 10 and any(character.islower() for character in text)


def _split_into_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [part.strip() for part in parts if part.strip()]
