from __future__ import annotations

from typing import Any, cast

import pytest

from article_to_speech.browser.capture import artifact_file_name
from article_to_speech.browser.support import final_artifact
from article_to_speech.core.models import AudioArtifact
from article_to_speech.infra.browser_audio_runtime import _extract_audio_sources_from_page


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

    async def evaluate(self, script: str) -> list[dict[str, str]]:
        assert "sourceUrls" in script
        return []


@pytest.mark.asyncio
async def test_extract_audio_sources_retries_until_timeout_when_page_exposes_nothing() -> None:
    page = IdleAudioPage()

    sources = await _extract_audio_sources_from_page(
        cast(Any, page),
        retries=3,
    )

    assert sources == []
    assert page.wait_calls == [1_000, 1_000, 1_000]
