from __future__ import annotations

from typing import Any, cast

import pytest

from article_to_speech.browser.capture import artifact_file_name
from article_to_speech.browser.support import final_artifact
from article_to_speech.core.models import AudioArtifact
from article_to_speech.infra.browser_audio_files import _write_network_payloads
from article_to_speech.infra.browser_audio_runtime import _wait_for_audio_completion


def test_write_network_payloads_deduplicates_repeated_audio_bytes(tmp_path) -> None:
    paths = _write_network_payloads(
        tmp_path,
        [
            ("https://example.com/audio-1.mp3", "audio/mpeg", b"segment-one"),
            ("https://example.com/audio-1.mp3", "audio/mpeg", b"segment-one"),
            ("https://example.com/audio-2.mp3", "audio/mpeg", b"segment-two"),
        ],
    )

    assert [path.name for path in paths] == ["network-audio-01.mp3", "network-audio-03.mp3"]
    assert paths[0].read_bytes() == b"segment-one"
    assert paths[1].read_bytes() == b"segment-two"


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


class IdleAudioPage:
    def __init__(self) -> None:
        self.wait_calls: list[int] = []

    async def wait_for_timeout(self, milliseconds: int) -> None:
        self.wait_calls.append(milliseconds)

    async def evaluate(self, script: str) -> dict[str, int]:
        assert "sourceCount" in script
        return {"sourceCount": 0, "playingCount": 0}


@pytest.mark.asyncio
async def test_wait_for_audio_completion_exits_when_audio_never_starts() -> None:
    page = IdleAudioPage()

    await _wait_for_audio_completion(
        cast(Any, page),
        [],
        [],
        timeout_ms=30_000,
        startup_timeout_ms=1_500,
    )

    assert sum(page.wait_calls) == 1_500
