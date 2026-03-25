from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from article_to_speech.core.exceptions import TelegramDeliveryError

LOGGER = logging.getLogger(__name__)


class TelegramBotClient:
    def __init__(self, token: str, *, timeout_seconds: float = 60.0) -> None:
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def get_me(self) -> dict[str, Any]:
        """Return the Telegram bot's own metadata."""
        return await self._request_json("GET", "/getMe")

    async def get_updates(self, offset: int | None, timeout_seconds: int) -> list[dict[str, Any]]:
        """Poll Telegram for inbound message updates."""
        payload: dict[str, Any] = {"timeout": timeout_seconds, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        response = await self._request_json("POST", "/getUpdates", json=payload)
        return list(response["result"])

    async def send_message(self, chat_id: int, text: str) -> None:
        """Send a text message back to Telegram."""
        await self._request_json(
            "POST",
            "/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        )

    async def set_message_reaction(self, chat_id: int, message_id: int, emoji: str) -> None:
        """Apply a simple emoji reaction to an existing Telegram message."""
        await self._request_json(
            "POST",
            "/setMessageReaction",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "reaction": [{"type": "emoji", "emoji": emoji}],
                "is_big": False,
            },
        )

    async def send_audio(self, chat_id: int, audio_path: Path, caption: str) -> None:
        """Upload an audio file to Telegram with a caption."""
        if not path_exists(audio_path):
            raise TelegramDeliveryError(f"Audio file does not exist: {audio_path}")
        with audio_path.open("rb") as file_handle:
            response = await self._client.post(
                self._base_url + "/sendAudio",
                data={"chat_id": str(chat_id), "caption": caption},
                files={"audio": (audio_path.name, file_handle, "audio/mpeg")},
            )
        self._raise_for_api_errors(response)

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self._client.request(method, self._base_url + path, **kwargs)
        self._raise_for_api_errors(response)
        payload = response.json()
        if not payload.get("ok", False):
            raise TelegramDeliveryError(str(payload))
        return payload

    @staticmethod
    def _raise_for_api_errors(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPError as error:
            LOGGER.error(
                "telegram_api_http_error",
                extra={"context": {"status": response.status_code}},
            )
            raise TelegramDeliveryError(str(error)) from error


def path_exists(path: Path) -> bool:
    """Return whether the given path exists."""
    return path.exists()
