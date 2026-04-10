from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Protocol

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from requests import Response

from article_to_speech.article.source_detection import detect_supported_source
from article_to_speech.core.config import Settings
from article_to_speech.core.exceptions import SpeechSynthesisError
from article_to_speech.core.models import AudioArtifact, NarrationChunk, ResolvedArticle
from article_to_speech.infra.audio import (
    artifact_dir,
    artifact_file_name,
    artifact_stem,
    build_final_artifact,
    write_audio_bytes,
)

_GOOGLE_TTS_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_GOOGLE_TTS_ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"
_VOICE_NAME_BY_SOURCE = {
    "nytimes": "en-US-Chirp3-HD-Kore",
    "zeit": "de-DE-Chirp3-HD-Kore",
    "spiegel": "de-DE-Chirp3-HD-Kore",
    "sueddeutsche": "de-DE-Chirp3-HD-Kore",
    "faz": "de-DE-Chirp3-HD-Kore",
    "spektrum": "de-DE-Chirp3-HD-Kore",
}


class _TextToSpeechClient(Protocol):
    def synthesize_speech(
        self,
        *,
        text: str,
        voice_name: str,
    ) -> bytes:
        """Return MP3 bytes for the provided article text and configured voice."""
        ...


class GoogleTextToSpeechSynthesizer:
    def __init__(
        self,
        settings: Settings,
        *,
        client: _TextToSpeechClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client or _build_client(settings.google_application_credentials)

    async def synthesize_article(
        self,
        article: ResolvedArticle,
        chunks: list[NarrationChunk],
    ) -> AudioArtifact:
        if not chunks:
            raise SpeechSynthesisError("No narration chunks were produced for synthesis.")
        voice_name = voice_name_for_article(article)
        chunk_outputs: list[Path] = []
        output_dir = artifact_dir(self._settings.artifacts_dir, article.title, article.final_url)
        final_output_path = output_dir / artifact_file_name(
            article.title, article.final_url, ".mp3"
        )
        for index, chunk in enumerate(chunks, start=1):
            output_path = (
                final_output_path
                if len(chunks) == 1
                else output_dir
                / f"{artifact_stem(article.title, article.final_url)}-chunk-{index:02d}.mp3"
            )
            try:
                payload = await asyncio.to_thread(
                    self._client.synthesize_speech,
                    text=chunk.text,
                    voice_name=voice_name,
                )
            except SpeechSynthesisError as error:
                raise SpeechSynthesisError(
                    f"Google TTS chunk {index}/{len(chunks)} failed: {error}"
                ) from error
            if not payload:
                raise SpeechSynthesisError("Google TTS returned an empty audio payload.")
            write_audio_bytes(output_path, payload, source_method="google_tts")
            chunk_outputs.append(output_path)
        return build_final_artifact(
            article.title,
            self._settings.artifacts_dir,
            chunk_outputs,
            article.final_url,
        )


def voice_name_for_article(article: ResolvedArticle) -> str:
    """Return the configured Google TTS voice for the article's supported source."""
    source = detect_supported_source(article.canonical_url)
    if source is None:
        raise SpeechSynthesisError(
            f"Unsupported article source for Google TTS voice mapping: {article.canonical_url}"
        )
    try:
        return _VOICE_NAME_BY_SOURCE[source.slug]
    except KeyError as error:
        raise SpeechSynthesisError(
            f"No Google TTS voice is configured for article source '{source.slug}'."
        ) from error


def _build_client(credentials_path: Path) -> GoogleTextToSpeechApiClient:
    return GoogleTextToSpeechApiClient(credentials_path)


class GoogleTextToSpeechApiClient:
    def __init__(self, credentials_path: Path) -> None:
        self._credentials = service_account.Credentials.from_service_account_file(
            str(credentials_path),
            scopes=[_GOOGLE_TTS_SCOPE],
        )
        self._request = Request()

    def synthesize_speech(
        self,
        *,
        text: str,
        voice_name: str,
    ) -> bytes:
        """Call the Google Cloud Text-to-Speech REST API and return MP3 bytes."""
        if not self._credentials.valid:
            self._credentials.refresh(self._request)
        response = _post_google_tts_request(self._credentials.token, text, voice_name)
        payload = _decode_audio_payload(response)
        if not isinstance(payload, str):
            raise SpeechSynthesisError("Google TTS response did not include audio content.")
        return base64.b64decode(payload)


def _voice_language_code(voice_name: str) -> str:
    return "-".join(voice_name.split("-", maxsplit=2)[:2])


def _post_google_tts_request(token: str | None, text: str, voice_name: str) -> Response:
    response = requests.post(
        _GOOGLE_TTS_ENDPOINT,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "input": {"text": text},
            "voice": {
                "languageCode": _voice_language_code(voice_name),
                "name": voice_name,
            },
            "audioConfig": {"audioEncoding": "MP3"},
        },
        timeout=60,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        raise SpeechSynthesisError(_google_tts_error_message(response)) from error
    except requests.RequestException as error:
        raise SpeechSynthesisError(f"Google TTS request failed: {error}") from error
    return response


def _decode_audio_payload(response: Response) -> str | None:
    return response.json().get("audioContent")


def _google_tts_error_message(response: Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        detail = response.text.strip() or f"HTTP {response.status_code}"
        return f"Google TTS request failed: {detail}"
    error_payload = payload.get("error")
    if isinstance(error_payload, dict):
        message = error_payload.get("message")
        status = error_payload.get("status")
        if isinstance(message, str) and message:
            if isinstance(status, str) and status:
                return f"Google TTS request failed ({status}): {message}"
            return f"Google TTS request failed: {message}"
    return f"Google TTS request failed: HTTP {response.status_code}"
