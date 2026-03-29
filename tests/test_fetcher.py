from __future__ import annotations

from pathlib import Path

import pytest

from article_to_speech.infra.archive_proxy import (
    archive_launch_proxies,
    archive_proxy_reaches_archive,
    dedupe_proxy_urls,
    filter_reachable_archive_proxy_urls,
    load_cached_archive_proxy_urls,
    parse_proxy_list,
    parse_proxy_settings,
    redact_proxy_url,
    resolve_archive_proxy_urls,
    write_cached_archive_proxy_urls,
)
from article_to_speech.browser.fetcher import (
    archive_lookup_urls,
    archive_lookup_url,
    looks_like_archive_challenge_page,
    looks_like_archive_listing_page,
    looks_like_archive_no_results_page,
)


def test_archive_lookup_url_wraps_target_url() -> None:
    url = "https://example.com/story"

    assert archive_lookup_url(url) == "https://archive.is/https://example.com/story"


def test_archive_lookup_urls_include_queryless_fallback() -> None:
    url = "https://example.com/story?ref=share&foo=bar"

    assert archive_lookup_urls(url) == (
        "https://archive.is/https://example.com/story?ref=share&foo=bar",
        "https://archive.is/https://example.com/story",
    )


def test_archive_lookup_urls_skip_duplicate_when_url_has_no_query() -> None:
    url = "https://example.com/story"

    assert archive_lookup_urls(url) == ("https://archive.is/https://example.com/story",)


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


def test_archive_no_results_page_detection_matches_empty_search_page() -> None:
    body = "archive.today\nwebpage capture\nNo results\nYou may want to archive this url"

    assert (
        looks_like_archive_no_results_page(
            "example title",
            body,
            "https://archive.is/https://example.com/story?ref=share",
        )
        is True
    )


def test_parse_proxy_settings_keeps_server_and_credentials() -> None:
    assert parse_proxy_settings("http://user:pass@proxy.example:8080") == {
        "server": "http://proxy.example:8080",
        "username": "user",
        "password": "pass",
    }


def test_archive_launch_proxies_append_direct_fallback() -> None:
    assert archive_launch_proxies(
        (
            "http://user1:pass1@proxy1.example:8080",
            "http://user2:pass2@proxy2.example:8081",
        )
    ) == (
        {
            "server": "http://proxy1.example:8080",
            "username": "user1",
            "password": "pass1",
        },
        {
            "server": "http://proxy2.example:8081",
            "username": "user2",
            "password": "pass2",
        },
        None,
    )


def test_parse_proxy_list_supports_webshare_download_format() -> None:
    assert parse_proxy_list("1.2.3.4:1111:user1:pass1\n5.6.7.8:2222:user2:pass2\n") == (
        "http://user1:pass1@1.2.3.4:1111",
        "http://user2:pass2@5.6.7.8:2222",
    )


def test_dedupe_proxy_urls_preserves_first_occurrence() -> None:
    assert dedupe_proxy_urls(
        (
            "http://user1:pass1@proxy1:1111",
            "http://user1:pass1@proxy1:1111",
            "http://user2:pass2@proxy2:2222",
        )
    ) == (
        "http://user1:pass1@proxy1:1111",
        "http://user2:pass2@proxy2:2222",
    )


def test_redact_proxy_url_hides_credentials() -> None:
    assert redact_proxy_url("http://user:pass@proxy.example:8080") == "http://proxy.example:8080"


def test_archive_proxy_cache_round_trip(tmp_path: Path) -> None:
    cache_path = tmp_path / "archive-proxies.txt"

    write_cached_archive_proxy_urls(
        cache_path,
        (
            "http://user1:pass1@proxy1:1111",
            "http://user1:pass1@proxy1:1111",
            "http://user2:pass2@proxy2:2222",
        ),
    )

    assert load_cached_archive_proxy_urls(cache_path) == (
        "http://user1:pass1@proxy1:1111",
        "http://user2:pass2@proxy2:2222",
    )


@pytest.mark.asyncio
async def test_filter_reachable_archive_proxy_urls_keep_working_proxies(monkeypatch) -> None:
    async def fake_probe(proxy_url: str, *, user_agent: str) -> bool:
        return proxy_url.endswith("good:1111")

    monkeypatch.setattr(
        "article_to_speech.infra.archive_proxy.archive_proxy_reaches_archive",
        fake_probe,
    )

    assert await filter_reachable_archive_proxy_urls(
        (
            "http://user1:pass1@good:1111",
            "http://user2:pass2@bad:2222",
        ),
        user_agent="test-agent",
    ) == ("http://user1:pass1@good:1111",)


@pytest.mark.asyncio
async def test_resolve_archive_proxy_urls_uses_working_configured_proxies_before_remote_list(
    monkeypatch,
) -> None:
    async def fake_download(proxy_list_url: str) -> tuple[str, ...]:
        raise AssertionError(f"download should not run for {proxy_list_url}")

    async def fake_filter(
        proxy_urls: tuple[str, ...],
        *,
        user_agent: str,
    ) -> tuple[str, ...]:
        assert user_agent == "test-agent"
        return proxy_urls[:2]

    monkeypatch.setattr(
        "article_to_speech.infra.archive_proxy.download_archive_proxy_urls",
        fake_download,
    )
    monkeypatch.setattr(
        "article_to_speech.infra.archive_proxy.filter_reachable_archive_proxy_urls",
        fake_filter,
    )

    assert await resolve_archive_proxy_urls(
        configured_urls=("http://user0:pass0@proxy0:0000",),
        proxy_list_url="https://proxy.example/list.txt",
        user_agent="test-agent",
        cache_path=None,
    ) == ("http://user0:pass0@proxy0:0000",)


@pytest.mark.asyncio
async def test_resolve_archive_proxy_urls_uses_cache_before_downloading(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "archive-proxies.txt"
    write_cached_archive_proxy_urls(cache_path, ("http://user1:pass1@cached:1111",))

    async def fake_filter(
        proxy_urls: tuple[str, ...],
        *,
        user_agent: str,
    ) -> tuple[str, ...]:
        assert user_agent == "test-agent"
        assert proxy_urls == ("http://user1:pass1@cached:1111",)
        return proxy_urls

    async def fake_download(proxy_list_url: str) -> tuple[str, ...]:
        raise AssertionError(f"download should not run for {proxy_list_url}")

    monkeypatch.setattr(
        "article_to_speech.infra.archive_proxy.filter_reachable_archive_proxy_urls",
        fake_filter,
    )
    monkeypatch.setattr(
        "article_to_speech.infra.archive_proxy.download_archive_proxy_urls",
        fake_download,
    )

    assert await resolve_archive_proxy_urls(
        configured_urls=(),
        proxy_list_url="https://proxy.example/list.txt",
        user_agent="test-agent",
        cache_path=cache_path,
    ) == ("http://user1:pass1@cached:1111",)


@pytest.mark.asyncio
async def test_resolve_archive_proxy_urls_refreshes_remote_list_when_cache_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "archive-proxies.txt"
    write_cached_archive_proxy_urls(cache_path, ("http://user1:pass1@cached:1111",))
    filter_calls: list[tuple[str, ...]] = []

    async def fake_filter(
        proxy_urls: tuple[str, ...],
        *,
        user_agent: str,
    ) -> tuple[str, ...]:
        filter_calls.append(proxy_urls)
        if proxy_urls == ("http://user1:pass1@cached:1111",):
            return ()
        return ("http://user2:pass2@fresh:2222",)

    async def fake_download(proxy_list_url: str) -> tuple[str, ...]:
        assert proxy_list_url == "https://proxy.example/list.txt"
        return ("http://user2:pass2@fresh:2222",)

    monkeypatch.setattr(
        "article_to_speech.infra.archive_proxy.filter_reachable_archive_proxy_urls",
        fake_filter,
    )
    monkeypatch.setattr(
        "article_to_speech.infra.archive_proxy.download_archive_proxy_urls",
        fake_download,
    )

    assert await resolve_archive_proxy_urls(
        configured_urls=(),
        proxy_list_url="https://proxy.example/list.txt",
        user_agent="test-agent",
        cache_path=cache_path,
    ) == ("http://user2:pass2@fresh:2222",)
    assert filter_calls == [
        ("http://user1:pass1@cached:1111",),
        ("http://user2:pass2@fresh:2222",),
    ]
    assert load_cached_archive_proxy_urls(cache_path) == ("http://user2:pass2@fresh:2222",)


@pytest.mark.asyncio
async def test_archive_proxy_reaches_archive_rejects_proxy_side_block(monkeypatch) -> None:
    class FakeResponse:
        status_code = 403
        headers = {"X-Webshare-Reason": "client_connect_forbidden_host"}

    class FakeClient:
        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str) -> FakeResponse:
            assert url == "https://archive.is/"
            return FakeResponse()

    monkeypatch.setattr(
        "article_to_speech.infra.archive_proxy.httpx.AsyncClient",
        lambda **_: FakeClient(),
    )

    assert (
        await archive_proxy_reaches_archive(
            "http://user:pass@proxy.example:8080",
            user_agent="test-agent",
        )
        is False
    )


@pytest.mark.asyncio
async def test_archive_proxy_reaches_archive_rejects_rate_limited_proxy(monkeypatch) -> None:
    class FakeResponse:
        status_code = 429
        headers: dict[str, str] = {}

    class FakeClient:
        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str) -> FakeResponse:
            assert url == "https://archive.is/"
            return FakeResponse()

    monkeypatch.setattr(
        "article_to_speech.infra.archive_proxy.httpx.AsyncClient",
        lambda **_: FakeClient(),
    )

    assert (
        await archive_proxy_reaches_archive(
            "http://user:pass@proxy.example:8080",
            user_agent="test-agent",
        )
        is False
    )
