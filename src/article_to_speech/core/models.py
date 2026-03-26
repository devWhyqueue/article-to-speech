from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class IncomingUrlJob:
    job_id: int
    chat_id: int
    message_id: int | None
    input_url: str
    created_at: datetime
    status: JobStatus
    attempts: int
    canonical_url: str | None = None
    last_error: str | None = None


@dataclass(slots=True, frozen=True)
class ResolvedArticle:
    canonical_url: str
    original_url: str
    final_url: str
    title: str
    source: str | None
    author: str | None
    published_at: str | None
    body_text: str
    paywalled: bool = False
    trace: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class NarrationRequest:
    article: ResolvedArticle
    prompt_text: str


@dataclass(slots=True, frozen=True)
class AudioArtifact:
    path: Path
    mime_type: str
    duration_seconds: float | None
    source_method: str
    sha256_hex: str


@dataclass(slots=True, frozen=True)
class FailureDetail:
    step: str
    message: str
    retryable: bool = False


@dataclass(slots=True, frozen=True)
class JobResult:
    job: IncomingUrlJob
    article: ResolvedArticle
    audio: AudioArtifact
    caption: str


@dataclass(slots=True)
class BrowserStepLog:
    step: str
    detail: str
    timestamp: datetime = field(default_factory=utc_now)
