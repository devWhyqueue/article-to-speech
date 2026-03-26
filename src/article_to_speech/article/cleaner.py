from __future__ import annotations

import re

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


class NarrationFormatter:
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
        """Build the ChatGPT narration request from the cleaned article body."""
        cleaned = self.clean_article_text(article)
        prompt_text = (
            "The user provided rough webpage text for a private accessibility read-aloud. "
            "Format nicely, i.e. start with heading and subtitle and main text after, "
            "all separated by newlines. Preserve original wording but remove obvious noise.\n\n"
            f"<text>\n{cleaned}\n</text>"
        )
        return [NarrationRequest(article=article, prompt_text=prompt_text)]


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
