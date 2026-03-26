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
    def clean_article_text(self, article: ResolvedArticle) -> str:
        """Convert markdown article content into narration-friendly plain text."""
        body = MULTI_NEWLINE_PATTERN.sub("\n\n", _clean_markdown_body(article.body_text)).strip()
        body = _trim_leading_noise(body)
        body = body.replace(HEADING_SENTINEL, "")
        parts = [article.title]
        if article.subtitle:
            parts.append(article.subtitle)
        if body:
            parts.append(body)
        return "\n\n".join(parts)

    def build_requests(self, article: ResolvedArticle) -> list[NarrationRequest]:
        """Build the ChatGPT narration request from the cleaned article body."""
        cleaned = self.clean_article_text(article)
        prompt_text = (
            "The user provided article text for a private accessibility read-aloud. "
            "Keep the title first, subtitle second when present, then the main text. "
            "Preserve wording, drop obvious noise, and do not read markdown punctuation literally.\n\n"
            f"<text>\n{cleaned}\n</text>"
        )
        return [NarrationRequest(article=article, prompt_text=prompt_text)]


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
