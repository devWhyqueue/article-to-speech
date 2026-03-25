from __future__ import annotations

from article_to_speech.browser.launch import _looks_like_missing_browser_dependency_error
from article_to_speech.browser.support import looks_like_challenge_page


def test_missing_browser_dependency_error_matches_shared_library_failure() -> None:
    message = "chrome: error while loading shared libraries: libnspr4.so: cannot open shared object file"

    assert _looks_like_missing_browser_dependency_error(message) is True


def test_missing_browser_dependency_error_matches_playwright_dependency_hint() -> None:
    message = "Host system is missing dependencies to run browsers."

    assert _looks_like_missing_browser_dependency_error(message) is True


def test_looks_like_challenge_page_matches_cloudflare_interstitial_text() -> None:
    body = "Enable JavaScript and cookies to continue"

    assert looks_like_challenge_page("ChatGPT", body, "https://chatgpt.com/") is True


def test_looks_like_challenge_page_matches_challenge_platform_url_marker() -> None:
    url = "https://chatgpt.com/cdn-cgi/challenge-platform/h/b/orchestrate/jsch/v1"

    assert looks_like_challenge_page("ChatGPT", "", url) is True
