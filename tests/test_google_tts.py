from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from article_to_speech.core.config import Settings
from article_to_speech.core.exceptions import SpeechSynthesisError
from article_to_speech.core.models import NarrationChunk, ResolvedArticle
from article_to_speech.tts.google import (
    GoogleTextToSpeechApiClient,
    GoogleTextToSpeechSynthesizer,
    voice_name_for_article,
)


class FakeTextToSpeechClient:
    def __init__(self, payloads: list[bytes]) -> None:
        self._payloads = list(payloads)
        self.calls: list[tuple[str, str]] = []

    def synthesize_speech(self, *, text: str, voice_name: str) -> bytes:
        self.calls.append((text, voice_name))
        return self._payloads.pop(0)


def _settings(tmp_path: Path) -> Settings:
    runtime_root = tmp_path / "runtime"
    return Settings(
        telegram_bot_token="token",
        telegram_allowed_chat_id=1,
        google_application_credentials=tmp_path / "service-account.json",
        runtime_root=runtime_root,
        state_db_path=runtime_root / "state" / "jobs.sqlite3",
        artifacts_dir=runtime_root / "artifacts",
        diagnostics_dir=runtime_root / "diagnostics",
        browser_headless=True,
        browser_locale="en-US",
        browser_timezone=None,
        archive_proxy_urls=(),
        archive_proxy_list_url=None,
    )


def _article(url: str, source_name: str) -> ResolvedArticle:
    return ResolvedArticle(
        canonical_url=url,
        original_url=url,
        final_url="https://archive.is/example",
        title="Example Headline",
        subtitle=None,
        source=source_name,
        author="Reporter",
        published_at="2026-04-02",
        body_text="Paragraph one.",
    )


async def test_google_tts_writes_single_chunk_mp3(tmp_path: Path) -> None:
    client = FakeTextToSpeechClient([b"single-chunk-audio"])
    synthesizer = GoogleTextToSpeechSynthesizer(_settings(tmp_path), client=client)

    artifact = await synthesizer.synthesize_article(
        _article("https://www.nytimes.com/example", "The New York Times"),
        [NarrationChunk(text="Single chunk text.")],
    )

    assert artifact.mime_type == "audio/mpeg"
    assert artifact.source_method == "single_chunk"
    assert artifact.path.read_bytes() == b"single-chunk-audio"
    assert client.calls == [("Single chunk text.", "en-US-Chirp3-HD-Kore")]


async def test_google_tts_concatenates_multiple_chunks(monkeypatch, tmp_path: Path) -> None:
    client = FakeTextToSpeechClient([b"chunk-one", b"chunk-two"])
    synthesizer = GoogleTextToSpeechSynthesizer(_settings(tmp_path), client=client)

    def fake_concat(
        title: str,
        artifacts_dir: Path,
        input_paths: list[Path],
        source_url: str | None = None,
    ):
        output_path = artifacts_dir / "joined.mp3"
        output_path.write_bytes(b"joined-audio")
        return SimpleNamespace(
            path=output_path,
            mime_type="audio/mpeg",
            duration_seconds=None,
            source_method="concat",
            sha256_hex="joined",
        )

    monkeypatch.setattr("article_to_speech.tts.google.build_final_artifact", fake_concat)

    artifact = await synthesizer.synthesize_article(
        _article("https://www.spiegel.de/example", "DER SPIEGEL"),
        [
            NarrationChunk(text="Erster Abschnitt."),
            NarrationChunk(text="Zweiter Abschnitt."),
        ],
    )

    assert artifact.source_method == "concat"
    assert artifact.path.read_bytes() == b"joined-audio"
    assert [voice_name for _, voice_name in client.calls] == [
        "de-DE-Chirp3-HD-Kore",
        "de-DE-Chirp3-HD-Kore",
    ]


def test_voice_name_for_article_uses_source_mapping() -> None:
    assert (
        voice_name_for_article(_article("https://www.nytimes.com/example", "The New York Times"))
        == "en-US-Chirp3-HD-Kore"
    )
    assert (
        voice_name_for_article(_article("https://www.zeit.de/example", "DIE ZEIT"))
        == "de-DE-Chirp3-HD-Kore"
    )
    assert (
        voice_name_for_article(_article("https://www.spektrum.de/news/example/123", "Spektrum.de"))
        == "de-DE-Chirp3-HD-Kore"
    )


def test_voice_name_for_article_rejects_unsupported_sources() -> None:
    article = _article("https://example.com/story", "Example News")

    with pytest.raises(SpeechSynthesisError, match="Unsupported article source"):
        voice_name_for_article(article)


async def test_google_tts_rejects_empty_audio_payload(tmp_path: Path) -> None:
    client = FakeTextToSpeechClient([b""])
    synthesizer = GoogleTextToSpeechSynthesizer(_settings(tmp_path), client=client)

    with pytest.raises(SpeechSynthesisError, match="empty audio payload"):
        await synthesizer.synthesize_article(
            _article("https://www.nytimes.com/example", "The New York Times"),
            [NarrationChunk(text="Single chunk text.")],
        )


def test_google_tts_surfaces_api_error_payload(monkeypatch) -> None:
    class FakeCredentials:
        valid = True
        token = "token"

        def refresh(self, request) -> None:
            return None

    response = requests.Response()
    response.status_code = 400
    response._content = (
        b'{"error":{"code":400,"message":"This request contains sentences that are too long.",'
        b'"status":"INVALID_ARGUMENT"}}'
    )
    response.url = "https://texttospeech.googleapis.com/v1/text:synthesize"
    response.request = requests.Request("POST", response.url).prepare()

    monkeypatch.setattr(
        "article_to_speech.tts.google.service_account.Credentials.from_service_account_file",
        lambda *_args, **_kwargs: FakeCredentials(),
    )
    monkeypatch.setattr("article_to_speech.tts.google.requests.post", lambda *args, **kwargs: response)

    client = GoogleTextToSpeechApiClient(Path("/tmp/service-account.json"))

    with pytest.raises(
        SpeechSynthesisError,
        match=r"INVALID_ARGUMENT\): This request contains sentences that are too long\.",
    ):
        client.synthesize_speech(
            text="Sentence.",
            voice_name="en-US-Chirp3-HD-Kore",
        )
