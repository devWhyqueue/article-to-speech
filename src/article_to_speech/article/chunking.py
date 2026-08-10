from __future__ import annotations

import re

from article_to_speech.article_helpers import (
    _hard_split_index_for_budget,
    _split_index_for_budget,
    _utf8_len,
)


def build_chunk_texts(
    intro_text: str,
    body: str,
    *,
    max_tts_input_bytes: int,
    max_sentence_bytes: int,
) -> list[str]:
    """Split intro + body into TTS-request-sized, per-sentence-safe chunks."""
    cleaned = f"{intro_text}\n\n{body}".strip() if body else intro_text
    if _fits_budget(cleaned, max_tts_input_bytes) and not _has_oversized_sentence(
        cleaned, max_sentence_bytes
    ):
        return [cleaned]
    body_segments = _split_body_segments(body, max_tts_input_bytes, max_sentence_bytes)
    return _assemble_chunk_texts(intro_text, body_segments, max_tts_input_bytes, max_sentence_bytes)


def _assemble_chunk_texts(
    intro_text: str,
    body_segments: list[str],
    max_tts_input_bytes: int,
    max_sentence_bytes: int,
) -> list[str]:
    chunks: list[str] = []
    current = intro_text
    remaining_segments = list(body_segments)
    if current and remaining_segments:
        first_candidate = f"{current}\n\n{remaining_segments[0]}"
        if not _fits_budget(first_candidate, max_tts_input_bytes) or _has_oversized_sentence(
            first_candidate, max_sentence_bytes
        ):
            # The intro (title/subtitle) has no terminal punctuation of its own, so
            # anything glued onto it is still "one sentence" to Google until real
            # punctuation shows up — bound the splice by the sentence budget, not
            # the larger chunk budget, and re-verify before committing to it.
            reserved = _utf8_len(current) + _utf8_len("\n\n")
            available = min(max_tts_input_bytes, max_sentence_bytes) - reserved
            if available > 0:
                split_segments = _split_text_to_fit(
                    remaining_segments.pop(0), available, max_sentence_bytes
                )
                merged = f"{current}\n\n{split_segments[0]}".strip()
                if _has_oversized_sentence(merged, max_sentence_bytes):
                    remaining_segments = split_segments + remaining_segments
                else:
                    current = merged
                    remaining_segments = split_segments[1:] + remaining_segments
    for segment in remaining_segments:
        candidate = f"{current}\n\n{segment}".strip() if current else segment
        if (
            candidate
            and _fits_budget(candidate, max_tts_input_bytes)
            and not _has_oversized_sentence(candidate, max_sentence_bytes)
        ):
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = segment
    if current:
        chunks.append(current)
    return chunks


def _split_body_segments(body: str, max_tts_input_bytes: int, max_sentence_bytes: int) -> list[str]:
    if not body:
        return []
    segments: list[str] = []
    for paragraph in body.split("\n\n"):
        if _fits_budget(paragraph, max_tts_input_bytes) and not _has_oversized_sentence(
            paragraph, max_sentence_bytes
        ):
            segments.append(paragraph)
            continue
        segments.extend(_split_text_to_fit(paragraph, max_tts_input_bytes, max_sentence_bytes))
    return segments


def _split_text_to_fit(text: str, text_budget: int, max_sentence_bytes: int) -> list[str]:
    if _fits_budget(text, text_budget) and not _has_oversized_sentence(text, max_sentence_bytes):
        return [text]
    sentences = _split_into_sentences(text)
    if len(sentences) == 1:
        return _hard_split(text, min(text_budget, max_sentence_bytes))
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence_parts = (
            [sentence]
            if _fits_budget(sentence, text_budget) and _fits_budget(sentence, max_sentence_bytes)
            else _hard_split(sentence, min(text_budget, max_sentence_bytes))
        )
        for part in sentence_parts:
            candidate = f"{current} {part}".strip() if current else part
            if candidate and _fits_budget(candidate, text_budget):
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = part
    if current:
        chunks.append(current)
    return chunks


def _has_oversized_sentence(text: str, max_sentence_bytes: int) -> bool:
    return any(
        not _fits_budget(sentence, max_sentence_bytes) for sentence in _split_into_sentences(text)
    )


def _hard_split(text: str, text_budget: int) -> list[str]:
    remaining = text.strip()
    # Reserve a byte for the sentence terminator appended below, so a forced
    # break never regrows past text_budget once punctuation is added back.
    fragment_budget = max(1, text_budget - 1)
    chunks: list[str] = []
    while remaining:
        if _fits_budget(remaining, fragment_budget):
            chunks.append(_terminate_fragment(remaining))
            break
        split_at = _split_index_for_budget(remaining, fragment_budget)
        if split_at <= 0:
            split_at = max(1, _hard_split_index_for_budget(remaining, fragment_budget))
        chunks.append(_terminate_fragment(remaining[:split_at].strip()))
        remaining = remaining[split_at:].strip()
    return chunks


def _fits_budget(text: str, text_budget: int) -> bool:
    return _utf8_len(text) <= text_budget


def _split_into_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [part.strip() for part in parts if part.strip()]


def _terminate_fragment(fragment: str) -> str:
    """Force a real sentence boundary onto a hard-split fragment.

    Downstream chunk assembly regroups fragments purely by byte budget; without a
    genuine terminator here, two adjacent fragments of one oversized run-on
    sentence could be rejoined into text Google's own tokenizer again treats as
    one too-long sentence.
    """
    return fragment if fragment.endswith((".", "!", "?")) else f"{fragment}."
