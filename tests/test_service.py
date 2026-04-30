from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from article_to_speech.core.exceptions import ArchivedPaywallError, SpeechSynthesisError
from article_to_speech.core.models import AudioArtifact, IncomingUrlJob, JobStatus, ResolvedArticle
from article_to_speech.service import ARCHIVED_PAYWALL_FEEDBACK, ArticleToSpeechService
from article_to_speech.telegram_support import build_caption


def test_build_caption_includes_archive_snapshot_link() -> None:
    article = ResolvedArticle(
        canonical_url="https://www.nytimes.com/example",
        original_url="https://www.nytimes.com/example",
        final_url="https://archive.is/SKNHa",
        title="Example Headline",
        subtitle=None,
        source="The New York Times",
        author="Ann E. Marimow",
        published_at="2026-03-24",
        body_text="Body text",
    )

    caption = build_caption(article)

    assert caption == (
        "Example Headline | The New York Times | Ann E. Marimow\nhttps://archive.is/SKNHa"
    )


def test_build_caption_skips_non_archive_final_url() -> None:
    article = ResolvedArticle(
        canonical_url="https://example.com/story",
        original_url="https://example.com/story",
        final_url="https://example.com/story",
        title="Example Headline",
        subtitle=None,
        source="Example News",
        author="Jane Doe",
        published_at="2026-03-24",
        body_text="Body text",
    )

    caption = build_caption(article)

    assert caption == "Example Headline | Example News | Jane Doe"


class StubStore:
    def mark_processing(self, job_id: int, canonical_url: str) -> IncomingUrlJob:
        return IncomingUrlJob(
            job_id=job_id,
            chat_id=123,
            message_id=99,
            input_url=canonical_url,
            created_at=datetime.now(UTC),
            status=JobStatus.PROCESSING,
            attempts=1,
            canonical_url=canonical_url,
        )

    def mark_succeeded(
        self,
        job_id: int,
        canonical_url: str,
        article_title: str,
        article_source: str | None,
        audio_path: str,
    ) -> None:
        return None

    def mark_failed(self, job_id: int, message: str) -> None:
        return None


class StubTelegram:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.audio_calls: list[tuple[int, Path, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))

    async def send_audio(self, chat_id: int, audio_path: Path, caption: str) -> None:
        self.audio_calls.append((chat_id, audio_path, caption))

    async def close(self) -> None:
        return None


class StubResolver:
    def __init__(self, article: ResolvedArticle) -> None:
        self.article = article

    async def resolve(self, input_url: str) -> ResolvedArticle:
        return self.article

    async def close(self) -> None:
        return None


class PaywalledStubResolver:
    async def resolve(self, input_url: str) -> ResolvedArticle:
        raise ArchivedPaywallError("Archive snapshot still shows the SPIEGEL+ paywall")

    async def close(self) -> None:
        return None


class StubSynthesizer:
    def __init__(self) -> None:
        self.chunks: list[str] = []

    async def synthesize_article(
        self, article: ResolvedArticle, chunks: list[Any]
    ) -> AudioArtifact:
        self.chunks = [chunk.text for chunk in chunks]
        return AudioArtifact(
            path=Path("/tmp/audio.mp3"),
            mime_type="audio/mpeg",
            duration_seconds=1.0,
            source_method="stub",
            sha256_hex="abc",
        )


class StubFormatter:
    def build_chunks(self, article: ResolvedArticle) -> list[Any]:
        return [type("Chunk", (), {"text": article.body_text})()]


async def test_process_job_sends_archive_lookup_link_before_audio() -> None:
    article = ResolvedArticle(
        canonical_url="https://example.com/story",
        original_url="https://example.com/story",
        final_url="https://archive.is/SKNHa",
        title="Example Headline",
        subtitle=None,
        source="Example News",
        author="Jane Doe",
        published_at="2026-03-24",
        body_text="Body text",
    )
    telegram = StubTelegram()
    service = ArticleToSpeechService(
        settings=cast(Any, object()),
        store=cast(Any, StubStore()),
        telegram=cast(Any, telegram),
        resolver=cast(Any, StubResolver(article)),
        synthesizer=cast(Any, StubSynthesizer()),
        formatter=cast(Any, StubFormatter()),
    )
    job = IncomingUrlJob(
        job_id=1,
        chat_id=123,
        message_id=99,
        input_url="https://example.com/story",
        created_at=datetime.now(UTC),
        status=JobStatus.QUEUED,
        attempts=0,
    )

    await service.process_job(job, notify_failures=True)

    assert telegram.messages == [(123, "Article link:\nhttps://archive.is/https://example.com/story")]
    assert len(telegram.audio_calls) == 1


async def test_process_job_skips_intermediate_message_for_non_archive_url() -> None:
    article = ResolvedArticle(
        canonical_url="https://example.com/story",
        original_url="https://example.com/story",
        final_url="https://example.com/story",
        title="Example Headline",
        subtitle=None,
        source="Example News",
        author="Jane Doe",
        published_at="2026-03-24",
        body_text="Body text",
    )
    telegram = StubTelegram()
    service = ArticleToSpeechService(
        settings=cast(Any, object()),
        store=cast(Any, StubStore()),
        telegram=cast(Any, telegram),
        resolver=cast(Any, StubResolver(article)),
        synthesizer=cast(Any, StubSynthesizer()),
        formatter=cast(Any, StubFormatter()),
    )
    job = IncomingUrlJob(
        job_id=1,
        chat_id=123,
        message_id=99,
        input_url="https://example.com/story",
        created_at=datetime.now(UTC),
        status=JobStatus.QUEUED,
        attempts=0,
    )

    await service.process_job(job, notify_failures=True)

    assert telegram.messages == []
    assert len(telegram.audio_calls) == 1


async def test_process_job_sends_single_audio_for_multiple_requests() -> None:
    article = ResolvedArticle(
        canonical_url="https://example.com/story",
        original_url="https://example.com/story",
        final_url="https://example.com/story",
        title="Example Headline",
        subtitle=None,
        source="Example News",
        author="Jane Doe",
        published_at="2026-03-24",
        body_text="Body text",
    )
    telegram = StubTelegram()
    synthesizer = StubSynthesizer()

    class MultiChunkFormatter:
        def build_chunks(self, article: ResolvedArticle) -> list[Any]:
            return [
                type("Chunk", (), {"text": f"{article.body_text} part 1"})(),
                type("Chunk", (), {"text": f"{article.body_text} part 2"})(),
            ]

    service = ArticleToSpeechService(
        settings=cast(Any, object()),
        store=cast(Any, StubStore()),
        telegram=cast(Any, telegram),
        resolver=cast(Any, StubResolver(article)),
        synthesizer=cast(Any, synthesizer),
        formatter=cast(Any, MultiChunkFormatter()),
    )
    job = IncomingUrlJob(
        job_id=1,
        chat_id=123,
        message_id=99,
        input_url="https://example.com/story",
        created_at=datetime.now(UTC),
        status=JobStatus.QUEUED,
        attempts=0,
    )

    await service.process_job(job, notify_failures=True)

    assert synthesizer.chunks == ["Body text part 1", "Body text part 2"]
    assert len(telegram.audio_calls) == 1


async def test_process_job_surfaces_synthesis_failures_to_telegram() -> None:
    article = ResolvedArticle(
        canonical_url="https://example.com/story",
        original_url="https://example.com/story",
        final_url="https://example.com/story",
        title="Example Headline",
        subtitle=None,
        source="Example News",
        author="Jane Doe",
        published_at="2026-03-24",
        body_text="Body text",
    )
    telegram = StubTelegram()

    class FailingSynthesizer:
        async def synthesize_article(self, article: ResolvedArticle, chunks: list[Any]) -> AudioArtifact:
            raise SpeechSynthesisError("Google TTS request failed")

    service = ArticleToSpeechService(
        settings=cast(Any, object()),
        store=cast(Any, StubStore()),
        telegram=cast(Any, telegram),
        resolver=cast(Any, StubResolver(article)),
        synthesizer=cast(Any, FailingSynthesizer()),
        formatter=cast(Any, StubFormatter()),
    )
    job = IncomingUrlJob(
        job_id=1,
        chat_id=123,
        message_id=99,
        input_url="https://example.com/story",
        created_at=datetime.now(UTC),
        status=JobStatus.QUEUED,
        attempts=0,
    )

    result = await service.process_job(job, notify_failures=True)

    assert result is None
    assert telegram.messages[-1] == (123, "Could not process that article: Google TTS request failed")


async def test_process_job_sends_dedicated_feedback_for_archived_spiegel_paywall() -> None:
    telegram = StubTelegram()
    synthesizer = StubSynthesizer()
    service = ArticleToSpeechService(
        settings=cast(Any, object()),
        store=cast(Any, StubStore()),
        telegram=cast(Any, telegram),
        resolver=cast(Any, PaywalledStubResolver()),
        synthesizer=cast(Any, synthesizer),
        formatter=cast(Any, StubFormatter()),
    )
    job = IncomingUrlJob(
        job_id=1,
        chat_id=123,
        message_id=99,
        input_url="https://www.spiegel.de/politik/deutschland/example.html",
        created_at=datetime.now(UTC),
        status=JobStatus.QUEUED,
        attempts=0,
    )

    result = await service.process_job(job, notify_failures=True)

    assert result is None
    assert telegram.messages == [(123, ARCHIVED_PAYWALL_FEEDBACK)]
    assert telegram.audio_calls == []
    assert synthesizer.chunks == []


async def test_process_job_skips_duplicate_non_queued_job() -> None:
    article = ResolvedArticle(
        canonical_url="https://example.com/story",
        original_url="https://example.com/story",
        final_url="https://archive.is/SKNHa",
        title="Example Headline",
        subtitle=None,
        source="Example News",
        author="Jane Doe",
        published_at="2026-03-24",
        body_text="Body text",
    )
    telegram = StubTelegram()
    service = ArticleToSpeechService(
        settings=cast(Any, object()),
        store=cast(Any, StubStore()),
        telegram=cast(Any, telegram),
        resolver=cast(Any, StubResolver(article)),
        synthesizer=cast(Any, StubSynthesizer()),
        formatter=cast(Any, StubFormatter()),
    )
    job = IncomingUrlJob(
        job_id=1,
        chat_id=123,
        message_id=99,
        input_url="https://example.com/story",
        created_at=datetime.now(UTC),
        status=JobStatus.FAILED,
        attempts=1,
    )

    result = await service.process_job(job, notify_failures=True)

    assert result is None
    assert telegram.messages == []
    assert telegram.audio_calls == []
