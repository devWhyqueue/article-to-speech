from __future__ import annotations

import re
from dataclasses import dataclass

from article_to_speech.core.models import NarrationRequest, ResolvedArticle

WHITESPACE_PATTERN = re.compile(r"[ \t]+")
MULTI_NEWLINE_PATTERN = re.compile(r"\n{3,}")
SHORT_LABEL_PATTERN = re.compile(r"^[A-Z0-9][A-Za-z0-9'’&:/ -]{0,48}$")
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


@dataclass(slots=True)
class NarrationFormatter:
    max_chars_per_chunk: int

    def clean_article_text(self, article: ResolvedArticle) -> str:
        """Remove obvious boilerplate while preserving the article wording."""
        lines = []
        for raw_line in article.body_text.splitlines():
            stripped = WHITESPACE_PATTERN.sub(" ", raw_line).strip()
            if not stripped:
                lines.append("")
                continue
            lowered = stripped.lower()
            if lowered.startswith(BOILERPLATE_PREFIXES):
                continue
            if _looks_like_chrome_label(stripped):
                continue
            lines.append(stripped)
        cleaned = MULTI_NEWLINE_PATTERN.sub("\n\n", "\n".join(lines)).strip()
        return _trim_leading_noise(cleaned)

    def build_requests(self, article: ResolvedArticle) -> list[NarrationRequest]:
        """Split a full article into prompt chunks for ChatGPT narration."""
        cleaned = self.clean_article_text(article)
        chunks = _chunk_text(cleaned, self.max_chars_per_chunk)
        requests: list[NarrationRequest] = []
        for index, chunk in enumerate(chunks, start=1):
            prompt_text = (
                "The user provided rough webpage text for a private accessibility read-aloud. "
                "Return only the main article body from that text. Remove obvious navigation, "
                "share labels, editor modules, related links, and other site chrome. Keep the "
                "actual article paragraphs in their original order and wording where possible. "
                "Do not add commentary or a summary.\n\n"
                f"Part {index} of {len(chunks)}\n"
                "Return only the text between <text> tags.\n\n"
                f"<text>\n{chunk}\n</text>"
            )
            requests.append(
                NarrationRequest(
                    article=article,
                    prompt_text=prompt_text,
                    chunk_index=index,
                    chunk_count=len(chunks),
                )
            )
        return requests


def _chunk_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= max_chars:
            current = paragraph
            continue
        start = 0
        while start < len(paragraph):
            chunks.append(paragraph[start : start + max_chars])
            start += max_chars
        current = ""
    if current:
        chunks.append(current)
    return chunks or [text]


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
        if _looks_like_sentence(line):
            return "\n\n".join(lines[index:])
    return "\n\n".join(lines)


def _looks_like_sentence(text: str) -> bool:
    if text.endswith((".", "!", "?")):
        return True
    words = text.split()
    return len(words) >= 10 and any(character.islower() for character in text)
