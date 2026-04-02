from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlparse, urlunparse

from article_to_speech.core.exceptions import InvalidUrlError

URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")
TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_", "cmpid", "sara_ref")
TRACKING_KEYS = {"share"}


def extract_first_url(message_text: str) -> str:
    """Extract the first usable URL from a Telegram message."""
    match = URL_PATTERN.search(message_text)
    if not match:
        raise InvalidUrlError("Telegram message does not contain a valid http/https URL.")
    return match.group(0).rstrip(").,]")


def normalize_url(url: str) -> str:
    """Normalize a URL by stripping fragments and common tracking parameters."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InvalidUrlError(f"Unsupported URL: {url}")
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith(TRACKING_PREFIXES) and key.lower() not in TRACKING_KEYS
    ]
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        fragment="",
        query="&".join(f"{key}={value}" if value else key for key, value in query),
    )
    return urlunparse(normalized)
