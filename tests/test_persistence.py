from pathlib import Path

import sqlite3

from article_to_speech.infra.persistence import JobStore


def test_job_store_round_trip(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    job = store.enqueue(chat_id=123, message_id=99, input_url="https://example.com/article")
    processing = store.mark_processing(job.job_id, "https://example.com/article")
    assert processing.attempts == 1
    store.mark_succeeded(
        processing.job_id,
        "https://example.com/article",
        "Title",
        "Example",
        "/tmp/audio.mp3",
    )
    with sqlite3.connect(tmp_path / "jobs.sqlite3") as connection:
        status, audio_path = connection.execute(
            "SELECT status, audio_path FROM jobs WHERE id = ?",
            (processing.job_id,),
        ).fetchone()
    assert status == "succeeded"
    assert audio_path == "/tmp/audio.mp3"
