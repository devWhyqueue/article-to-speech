from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

from article_to_speech.core.exceptions import InvalidUrlError, TelegramConflictError
from article_to_speech.core.models import IncomingUrlJob, JobStatus
from article_to_speech.service import PROCESSING_REACTION_EMOJI, TelegramPollingRunner


class FakeService:
    def __init__(self, *, should_raise_invalid_url: bool = False) -> None:
        self.should_raise_invalid_url = should_raise_invalid_url
        self.enqueued_jobs: list[IncomingUrlJob] = []
        self.processed_jobs: list[tuple[IncomingUrlJob, bool]] = []

    def enqueue_from_message(self, *, chat_id: int, message_id: int | None, text: str) -> IncomingUrlJob:
        if self.should_raise_invalid_url:
            raise InvalidUrlError("Message must contain a URL.")
        job = IncomingUrlJob(
            job_id=1,
            chat_id=chat_id,
            message_id=message_id,
            input_url=text,
            created_at=datetime.now(UTC),
            status=JobStatus.QUEUED,
            attempts=0,
        )
        self.enqueued_jobs.append(job)
        return job

    async def process_job(self, job: IncomingUrlJob, *, notify_failures: bool) -> None:
        self.processed_jobs.append((replace(job), notify_failures))


class FakeTelegram:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.reactions: list[tuple[int, int, str]] = []
        self.deleted_webhook = False
        self.get_me_called = False
        self.get_updates_calls: list[tuple[int | None, int]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))

    async def set_message_reaction(self, chat_id: int, message_id: int, emoji: str) -> None:
        self.reactions.append((chat_id, message_id, emoji))

    async def delete_webhook(self) -> None:
        self.deleted_webhook = True

    async def get_me(self) -> dict[str, object]:
        self.get_me_called = True
        return {"ok": True}

    async def get_updates(self, offset: int | None, timeout_seconds: int) -> list[dict[str, object]]:
        self.get_updates_calls.append((offset, timeout_seconds))
        raise RuntimeError("stop")


def _settings() -> object:
    class Settings:
        telegram_allowed_chat_id = 123
        telegram_poll_timeout_seconds = 30

    return Settings()


async def test_runner_sets_processing_reaction_for_valid_article_message() -> None:
    service = FakeService()
    telegram = FakeTelegram()
    runner = TelegramPollingRunner(cast(Any, _settings()), cast(Any, service), cast(Any, telegram))

    await runner._handle_update(
        {
            "update_id": 1,
            "message": {
                "message_id": 99,
                "chat": {"id": 123},
                "text": "https://example.com/article",
            },
        }
    )

    assert telegram.reactions == [(123, 99, PROCESSING_REACTION_EMOJI)]
    assert telegram.messages == []
    assert len(service.processed_jobs) == 1
    assert service.processed_jobs[0][1] is True


async def test_runner_skips_processing_reaction_for_invalid_message() -> None:
    service = FakeService(should_raise_invalid_url=True)
    telegram = FakeTelegram()
    runner = TelegramPollingRunner(cast(Any, _settings()), cast(Any, service), cast(Any, telegram))

    await runner._handle_update(
        {
            "update_id": 1,
            "message": {
                "message_id": 99,
                "chat": {"id": 123},
                "text": "not a url",
            },
        }
    )

    assert telegram.reactions == []
    assert telegram.messages == [(123, "Message must contain a URL.")]
    assert service.processed_jobs == []


async def test_runner_disables_webhook_before_polling() -> None:
    service = FakeService()
    telegram = FakeTelegram()
    runner = TelegramPollingRunner(cast(Any, _settings()), cast(Any, service), cast(Any, telegram))

    try:
        await runner.run()
    except RuntimeError as error:
        assert str(error) == "stop"

    assert telegram.deleted_webhook is True
    assert telegram.get_me_called is True
    assert telegram.get_updates_calls == [(None, 30)]


async def test_runner_retries_after_transient_poll_conflict() -> None:
    service = FakeService()

    class ConflictThenStopTelegram(FakeTelegram):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        async def get_updates(
            self, offset: int | None, timeout_seconds: int
        ) -> list[dict[str, object]]:
            self.get_updates_calls.append((offset, timeout_seconds))
            self.calls += 1
            if self.calls == 1:
                raise TelegramConflictError("terminated by other getUpdates request")
            raise RuntimeError("stop")

    telegram = ConflictThenStopTelegram()
    runner = TelegramPollingRunner(cast(Any, _settings()), cast(Any, service), cast(Any, telegram))

    try:
        await runner.run()
    except RuntimeError as error:
        assert str(error) == "stop"

    assert telegram.deleted_webhook is True
    assert telegram.get_updates_calls == [(None, 30), (None, 30)]
