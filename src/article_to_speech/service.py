from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import replace

from article_to_speech.article.cleaner import NarrationFormatter
from article_to_speech.article.resolver import ArticleResolver
from article_to_speech.browser.chatgpt import ChatGPTBrowserAutomation
from article_to_speech.core.config import Settings
from article_to_speech.core.exceptions import (
    ArticleToSpeechError,
    InvalidUrlError,
    TelegramConflictError,
)
from article_to_speech.core.models import IncomingUrlJob, JobResult, JobStatus
from article_to_speech.core.urls import extract_first_url, normalize_url
from article_to_speech.infra.persistence import JobStore
from article_to_speech.infra.telegram import TelegramBotClient
from article_to_speech.telegram_support import build_caption, build_intermediate_article_link

LOGGER = logging.getLogger(__name__)
PROCESSING_REACTION_EMOJI = "⏳"


class ArticleToSpeechService:
    def __init__(
        self,
        *,
        settings: Settings,
        store: JobStore,
        telegram: TelegramBotClient,
        resolver: ArticleResolver,
        browser: ChatGPTBrowserAutomation,
        formatter: NarrationFormatter,
    ) -> None:
        self._store = store
        self._telegram = telegram
        self._resolver = resolver
        self._browser = browser
        self._formatter = formatter
        self._serial_lock = asyncio.Lock()

    async def close(self) -> None:
        await self._telegram.close()
        await self._resolver.close()

    async def process_existing_pending_jobs(self) -> None:
        for job in self._store.list_pending():
            await self.process_job(job, notify_failures=False)

    def enqueue_from_message(
        self,
        *,
        chat_id: int,
        message_id: int | None,
        text: str,
    ) -> IncomingUrlJob:
        """Create a queued job from an inbound Telegram message."""
        url = extract_first_url(text)
        return self._store.enqueue(chat_id=chat_id, message_id=message_id, input_url=url)

    async def process_job(self, job: IncomingUrlJob, *, notify_failures: bool) -> JobResult | None:
        async with self._serial_lock:
            try:
                canonical_url = normalize_url(job.input_url)
                processing_job = self._store.mark_processing(job.job_id, canonical_url)
                LOGGER.info(
                    "process_job",
                    extra={"context": {"job_id": processing_job.job_id, "url": canonical_url}},
                )
                article = await self._resolver.resolve(processing_job.input_url)
                await self._send_article_link(
                    processing_job.chat_id, build_intermediate_article_link(article)
                )
                requests = self._formatter.build_requests(article)
                audio = await self._browser.synthesize_article(article, requests)
                caption = build_caption(article)
                await self._telegram.send_audio(processing_job.chat_id, audio.path, caption)
                self._store.mark_succeeded(
                    processing_job.job_id,
                    article.canonical_url,
                    article.title,
                    article.source,
                    str(audio.path),
                )
                completed_job = replace(processing_job, status=JobStatus.SUCCEEDED)
                return JobResult(job=completed_job, article=article, audio=audio, caption=caption)
            except ArticleToSpeechError as error:
                self._store.mark_failed(job.job_id, str(error))
                LOGGER.error(
                    "process_job_failed",
                    extra={"context": {"job_id": job.job_id, "error": str(error)}},
                )
                if notify_failures:
                    await self._telegram.send_message(
                        job.chat_id, f"Could not process that article: {error}"
                    )
                return None

    async def _send_article_link(self, chat_id: int, message: str | None) -> None:
        if message is None:
            return
        try:
            await self._telegram.send_message(chat_id, message)
        except ArticleToSpeechError as error:
            LOGGER.warning(
                "send_article_link_failed",
                extra={"context": {"chat_id": chat_id, "message": message, "error": str(error)}},
            )


class TelegramPollingRunner:
    def __init__(
        self, settings: Settings, service: ArticleToSpeechService, telegram: TelegramBotClient
    ) -> None:
        self._settings = settings
        self._service = service
        self._telegram = telegram
        self._next_update_offset: int | None = None

    async def run(self) -> None:
        await self._service.process_existing_pending_jobs()
        await self._telegram.delete_webhook()
        await self._telegram.get_me()
        while True:
            try:
                updates = await self._telegram.get_updates(
                    self._next_update_offset,
                    self._settings.telegram_poll_timeout_seconds,
                )
            except TelegramConflictError as error:
                LOGGER.warning(
                    "telegram_poll_conflict",
                    extra={"context": {"error": str(error)}},
                )
                await asyncio.sleep(2)
                continue
            for update in updates:
                self._next_update_offset = int(update["update_id"]) + 1
                await self._handle_update(update)

    async def _handle_update(self, update: dict[str, object]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return
        chat_id = int(chat["id"])
        if chat_id != self._settings.telegram_allowed_chat_id:
            LOGGER.info("ignoring_unauthorized_chat", extra={"context": {"chat_id": chat_id}})
            return
        text = message.get("text") or message.get("caption")
        if not isinstance(text, str):
            await self._telegram.send_message(
                chat_id, "Send a message containing a single article URL."
            )
            return
        try:
            job = self._service.enqueue_from_message(
                chat_id=chat_id,
                message_id=int(message["message_id"]),
                text=text,
            )
        except InvalidUrlError as error:
            await self._telegram.send_message(chat_id, str(error))
            return
        if job.message_id is not None:
            await self._set_processing_reaction(chat_id, job.message_id)
        await self._service.process_job(job, notify_failures=True)

    async def _set_processing_reaction(self, chat_id: int, message_id: int) -> None:
        try:
            await self._telegram.set_message_reaction(
                chat_id, message_id, PROCESSING_REACTION_EMOJI
            )
        except ArticleToSpeechError as error:
            LOGGER.warning(
                "set_processing_reaction_failed",
                extra={
                    "context": {
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "error": str(error),
                    }
                },
            )


def build_service(settings: Settings) -> ArticleToSpeechService:
    """Build a fully wired service instance from application settings."""
    store = JobStore(settings.state_db_path)
    store.initialize()
    return ArticleToSpeechService(
        settings=settings,
        store=store,
        telegram=TelegramBotClient(settings.telegram_bot_token),
        resolver=ArticleResolver(settings),
        browser=ChatGPTBrowserAutomation(settings),
        formatter=NarrationFormatter(settings.max_article_chars_per_chunk),
    )


async def run_bot(settings: Settings) -> None:
    service = build_service(settings)
    runner = TelegramPollingRunner(settings, service, service._telegram)
    try:
        await runner.run()
    finally:
        await service.close()


async def run_process_url(settings: Settings, args: argparse.Namespace) -> int:
    service = build_service(settings)
    try:
        chat_id = args.chat_id or settings.telegram_allowed_chat_id
        job = service.enqueue_from_message(chat_id=chat_id, message_id=None, text=args.url)
        result = await service.process_job(job, notify_failures=True)
        return 0 if result else 1
    finally:
        await service.close()


async def run_validate_live(settings: Settings, args: argparse.Namespace) -> int:
    service = build_service(settings)
    urls = list(args.urls)
    exit_code = 0
    try:
        for url in urls:
            job = service.enqueue_from_message(
                chat_id=settings.telegram_allowed_chat_id, message_id=None, text=url
            )
            result = await service.process_job(job, notify_failures=True)
            if result is None:
                exit_code = 1
        return exit_code
    finally:
        await service.close()


async def run_setup_browser(settings: Settings) -> None:
    await ChatGPTBrowserAutomation(settings).bootstrap_login()
