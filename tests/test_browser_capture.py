from __future__ import annotations

import pytest
from playwright.async_api import Page, Response
from typing import cast

from article_to_speech.browser.capture import artifact_file_name, maybe_capture_response_bytes
from article_to_speech.browser.support import capture_audio_chunk, final_artifact
from article_to_speech.core.models import AudioArtifact
from article_to_speech.infra.browser_audio_files import (
    _wait_for_audio_response_payload,
    _write_network_payloads,
)


def test_artifact_file_name_includes_archive_snapshot_id() -> None:
    name = artifact_file_name(
        "Supreme Court Seems Open to Trump Request to Block Asylum Seekers at Border",
        "https://archive.is/SKNHa",
        ".mp3",
    )

    assert name == "supreme-court-seems-open-to-trump-request-to-block-asylum-seekers-at-border-sknha.mp3"


def test_final_artifact_copies_single_chunk_to_descriptive_output(tmp_path) -> None:
    chunk_path = tmp_path / "chunk.mp3"
    chunk_path.write_bytes(b"single-chunk-audio")

    artifact = final_artifact(
        "Supreme Court Seems Open to Trump Request to Block Asylum Seekers at Border",
        tmp_path,
        [chunk_path],
        "https://archive.is/SKNHa",
    )

    assert isinstance(artifact, AudioArtifact)
    assert artifact.path.name == (
        "supreme-court-seems-open-to-trump-request-to-block-asylum-seekers-at-border-sknha.mp3"
    )
    assert artifact.path.read_bytes() == b"single-chunk-audio"


class FakeResponse:
    def __init__(self, url: str, content_type: str, payload: bytes) -> None:
        self.url = url
        self.headers = {"content-type": content_type}
        self._payload = payload

    async def body(self) -> bytes:
        return self._payload


class WaitingPage:
    def __init__(self) -> None:
        self.wait_calls: list[int] = []

    async def wait_for_timeout(self, milliseconds: int) -> None:
        self.wait_calls.append(milliseconds)


class FakeTurnLocator:
    @property
    def last(self) -> FakeTurnLocator:
        return self


class FakeAudioButton:
    def __init__(self) -> None:
        self.clicks = 0

    async def click(self, timeout: int) -> None:
        self.clicks += 1


class FakeCapturePage(WaitingPage):
    def __init__(self) -> None:
        super().__init__()
        self.load_state_calls: list[tuple[str, int]] = []
        self.reload_calls: list[tuple[str, int]] = []
        self.function_timeouts: list[int] = []

    def locator(self, selector: str) -> FakeTurnLocator:
        assert selector == "section[data-turn='assistant']"
        return FakeTurnLocator()

    async def reload(self, *, wait_until: str, timeout: int) -> None:
        self.reload_calls.append((wait_until, timeout))

    async def wait_for_load_state(self, state: str, timeout: int) -> None:
        self.load_state_calls.append((state, timeout))

    async def wait_for_function(self, expression: str, *, timeout: int) -> None:
        self.function_timeouts.append(timeout)


@pytest.mark.asyncio
async def test_maybe_capture_response_bytes_accepts_chatgpt_synthesize_url() -> None:
    payloads: list[tuple[str, str, bytes]] = []
    response = FakeResponse(
        "https://chatgpt.com/backend-api/synthesize?message_id=abc&format=aac",
        "application/octet-stream",
        b"aac-payload",
    )

    await maybe_capture_response_bytes(response=cast(Response, response), payloads=payloads)

    assert payloads == [
        (
            "https://chatgpt.com/backend-api/synthesize?message_id=abc&format=aac",
            "application/octet-stream",
            b"aac-payload",
        )
    ]


@pytest.mark.asyncio
async def test_wait_for_audio_response_payload_returns_when_payload_appears() -> None:
    page = WaitingPage()
    response_payloads: list[tuple[str, str, bytes]] = []

    async def inject_payload() -> None:
        if len(page.wait_calls) == 2 and not response_payloads:
            response_payloads.append(("https://chatgpt.com/backend-api/synthesize", "audio/aac", b"x"))

    original_wait = page.wait_for_timeout

    async def instrumented_wait(milliseconds: int) -> None:
        await original_wait(milliseconds)
        await inject_payload()

    page.wait_for_timeout = instrumented_wait  # type: ignore[method-assign]

    await _wait_for_audio_response_payload(
        cast(Page, page), response_payloads, timeout_ms=5_000
    )

    assert page.wait_calls == [500, 500]


@pytest.mark.asyncio
async def test_wait_for_audio_response_payload_times_out_without_payload() -> None:
    page = WaitingPage()

    with pytest.raises(TimeoutError, match="Timed out waiting for the ChatGPT synthesize response."):
        await _wait_for_audio_response_payload(cast(Page, page), [], timeout_ms=1_500)

    assert page.wait_calls == [500, 500, 500]


@pytest.mark.asyncio
async def test_capture_audio_chunk_retries_once_after_refresh(monkeypatch, tmp_path) -> None:
    page = FakeCapturePage()
    button = FakeAudioButton()
    response_payloads: list[tuple[str, str, bytes]] = []
    wait_calls = 0
    recovery_calls = 0

    async def fake_locate_read_aloud_button(turn, page_arg):
        assert page_arg is page
        return button

    async def fake_wait_for_audio_response_payload(page_arg, payloads, *, timeout_ms: int) -> None:
        nonlocal wait_calls
        assert page_arg is page
        wait_calls += 1
        if wait_calls == 1:
            raise TimeoutError("Timed out waiting for the ChatGPT synthesize response.")
        payloads.append(("https://chatgpt.com/backend-api/synthesize", "audio/mpeg", b"retry-ok"))

    async def fake_stop_audio_playback(page_arg) -> None:
        assert page_arg is page

    async def fake_recover_audio_capture_page(page_arg, settle_ms: int) -> None:
        nonlocal recovery_calls
        assert page_arg is page
        assert settle_ms == 5_000
        recovery_calls += 1

    monkeypatch.setattr(
        "article_to_speech.browser.support.locate_read_aloud_button",
        fake_locate_read_aloud_button,
    )
    monkeypatch.setattr(
        "article_to_speech.browser.support._wait_for_audio_response_payload",
        fake_wait_for_audio_response_payload,
    )
    monkeypatch.setattr(
        "article_to_speech.browser.support._stop_audio_playback",
        fake_stop_audio_playback,
    )
    monkeypatch.setattr(
        "article_to_speech.browser.support.recover_audio_capture_page",
        fake_recover_audio_capture_page,
    )

    paths = await capture_audio_chunk(
        page=cast(Page, page),
        downloads=[],
        response_payloads=response_payloads,
        diagnostics_dir=tmp_path,
        chunk_index=1,
    )

    assert recovery_calls == 1
    assert wait_calls == 2
    assert button.clicks == 2
    assert [path.name for path in paths] == ["network-audio.mp3"]


@pytest.mark.asyncio
async def test_capture_audio_chunk_raises_after_retry_exhausted(monkeypatch, tmp_path) -> None:
    page = FakeCapturePage()
    button = FakeAudioButton()
    recovery_calls = 0

    async def fake_locate_read_aloud_button(turn, page_arg):
        assert page_arg is page
        return button

    async def fake_wait_for_audio_response_payload(page_arg, payloads, *, timeout_ms: int) -> None:
        raise TimeoutError("Timed out waiting for the ChatGPT synthesize response.")

    async def fake_stop_audio_playback(page_arg) -> None:
        assert page_arg is page

    async def fake_recover_audio_capture_page(page_arg, settle_ms: int) -> None:
        nonlocal recovery_calls
        assert page_arg is page
        assert settle_ms == 5_000
        recovery_calls += 1

    monkeypatch.setattr(
        "article_to_speech.browser.support.locate_read_aloud_button",
        fake_locate_read_aloud_button,
    )
    monkeypatch.setattr(
        "article_to_speech.browser.support._wait_for_audio_response_payload",
        fake_wait_for_audio_response_payload,
    )
    monkeypatch.setattr(
        "article_to_speech.browser.support._stop_audio_playback",
        fake_stop_audio_playback,
    )
    monkeypatch.setattr(
        "article_to_speech.browser.support.recover_audio_capture_page",
        fake_recover_audio_capture_page,
    )

    with pytest.raises(TimeoutError, match="Timed out waiting for the ChatGPT synthesize response."):
        await capture_audio_chunk(
            page=cast(Page, page),
            downloads=[],
            response_payloads=[],
            diagnostics_dir=tmp_path,
            chunk_index=1,
        )

    assert recovery_calls == 1
    assert button.clicks == 2


def test_write_network_payloads_uses_sequential_names_for_multiple_payloads(tmp_path) -> None:
    paths = _write_network_payloads(
        tmp_path,
        [
            ("https://chatgpt.com/backend-api/synthesize?part=1", "audio/mpeg", b"chunk-one"),
            ("https://chatgpt.com/backend-api/synthesize?part=2", "audio/mpeg", b"chunk-two"),
        ],
    )

    assert [path.name for path in paths] == ["network-audio-01.mp3", "network-audio-02.mp3"]
