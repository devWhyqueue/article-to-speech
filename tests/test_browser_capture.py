from __future__ import annotations

import pytest

from article_to_speech.browser.capture import artifact_file_name, maybe_capture_response_bytes
from article_to_speech.browser.support import final_artifact
from article_to_speech.core.models import AudioArtifact
from article_to_speech.infra.browser_audio_files import (
    _looks_like_full_sized_chatgpt_chunk,
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


@pytest.mark.asyncio
async def test_maybe_capture_response_bytes_accepts_chatgpt_synthesize_url() -> None:
    payloads: list[tuple[str, str, bytes]] = []
    response = FakeResponse(
        "https://chatgpt.com/backend-api/synthesize?message_id=abc&format=aac",
        "application/octet-stream",
        b"aac-payload",
    )

    await maybe_capture_response_bytes(response, payloads)

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

    await _wait_for_audio_response_payload(page, response_payloads, timeout_ms=5_000)

    assert page.wait_calls == [500, 500]


@pytest.mark.asyncio
async def test_wait_for_audio_response_payload_waits_for_next_payload_count() -> None:
    page = WaitingPage()
    response_payloads = [("https://chatgpt.com/backend-api/synthesize", "audio/aac", b"first")]

    async def inject_payload() -> None:
        if len(page.wait_calls) == 3 and len(response_payloads) == 1:
            response_payloads.append(
                ("https://chatgpt.com/backend-api/synthesize", "audio/aac", b"second")
            )

    original_wait = page.wait_for_timeout

    async def instrumented_wait(milliseconds: int) -> None:
        await original_wait(milliseconds)
        await inject_payload()

    page.wait_for_timeout = instrumented_wait  # type: ignore[method-assign]

    await _wait_for_audio_response_payload(
        page,
        response_payloads,
        timeout_ms=5_000,
        minimum_payload_count=2,
    )

    assert page.wait_calls == [500, 500, 500]


@pytest.mark.asyncio
async def test_wait_for_audio_response_payload_times_out_without_payload() -> None:
    page = WaitingPage()

    with pytest.raises(TimeoutError, match="Timed out waiting for the ChatGPT synthesize response."):
        await _wait_for_audio_response_payload(page, [], timeout_ms=1_500)

    assert page.wait_calls == [500, 500, 500]


def test_write_network_payloads_uses_sequential_names_for_followup_chunks(tmp_path) -> None:
    paths = _write_network_payloads(
        tmp_path,
        [
            ("https://chatgpt.com/backend-api/synthesize?part=2", "audio/mpeg", b"chunk-two"),
            ("https://chatgpt.com/backend-api/synthesize?part=3", "audio/mpeg", b"chunk-three"),
        ],
        start_index=2,
    )

    assert [path.name for path in paths] == ["network-audio-02.mp3", "network-audio-03.mp3"]


def test_looks_like_full_sized_chatgpt_chunk_detects_five_minute_boundaries() -> None:
    assert _looks_like_full_sized_chatgpt_chunk(300.0) is True
    assert _looks_like_full_sized_chatgpt_chunk(297.4) is True
    assert _looks_like_full_sized_chatgpt_chunk(303.2) is False
    assert _looks_like_full_sized_chatgpt_chunk(250.0) is False
    assert _looks_like_full_sized_chatgpt_chunk(None) is False
