from __future__ import annotations

from article_to_speech.browser.fetcher import (
    archive_lookup_url,
    looks_like_archive_challenge_page,
    looks_like_archive_listing_page,
)


def test_archive_lookup_url_wraps_target_url() -> None:
    url = "https://example.com/story"

    assert archive_lookup_url(url) == "https://archive.is/https://example.com/story"


def test_archive_challenge_page_detection_matches_recaptcha_gate() -> None:
    body = "One more step\nPlease complete the security check to access archive.is"

    assert looks_like_archive_challenge_page("archive.is", body, "https://archive.is/") is True


def test_archive_listing_page_detection_matches_snapshot_index() -> None:
    body = "archive.today\nList of URLs, ordered from newer to older\nOldest Newest"

    assert (
        looks_like_archive_listing_page(
            "example title",
            body,
            "https://archive.is/https://example.com/story",
        )
        is True
    )
