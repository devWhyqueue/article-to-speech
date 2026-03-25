from pathlib import Path

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
    pending = store.list_pending()
    assert pending == []
