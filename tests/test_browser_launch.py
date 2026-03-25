from __future__ import annotations

import json
from typing import Any, cast

import pytest

from article_to_speech.browser.capture import collect_browser_snapshot
from article_to_speech.browser.launch import browser_args, build_browser_context_options
from article_to_speech.core.config import Settings


def _write_env_file(tmp_path, *extra_lines: str) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_CHAT_ID=123",
                "CHATGPT_PROJECT_NAME=Articles",
                *extra_lines,
            ]
        ),
        encoding="utf-8",
    )


def test_build_browser_context_options_keep_existing_args_and_skip_user_agent(
    tmp_path, monkeypatch
) -> None:
    _write_env_file(tmp_path)

    monkeypatch.delenv("DISPLAY", raising=False)
    settings = Settings.load(tmp_path)
    options = build_browser_context_options(settings)
    args = cast(list[str], options["args"])

    assert options["headless"] is True
    assert options["accept_downloads"] is True
    assert options["locale"] == "en-US"
    assert args == browser_args()
    assert "--disable-blink-features=AutomationControlled" in args
    assert "--start-maximized" in args
    assert "user_agent" not in options
    assert "timezone_id" not in options


def test_build_browser_context_options_include_timezone_override(tmp_path) -> None:
    _write_env_file(
        tmp_path,
        "CHATGPT_BROWSER_LOCALE=de-DE",
        "CHATGPT_BROWSER_TIMEZONE=Europe/Berlin",
    )

    settings = Settings.load(tmp_path)
    options = build_browser_context_options(settings)

    assert options["locale"] == "de-DE"
    assert options.get("timezone_id") == "Europe/Berlin"


class FakePage:
    url = "https://chatgpt.com/"

    async def evaluate(self, script: str) -> dict[str, object]:
        assert "navigator.userAgent" in script
        return {
            "navigator": {
                "userAgent": "Mozilla/5.0",
                "language": "en-US",
                "languages": ["en-US", "en"],
                "platform": "Linux x86_64",
                "webdriver": False,
                "hardwareConcurrency": 8,
                "deviceMemory": 8,
                "plugins": 5,
            },
            "window": {
                "innerWidth": 1440,
                "innerHeight": 960,
                "outerWidth": 1440,
                "outerHeight": 960,
                "devicePixelRatio": 1,
            },
            "screen": {
                "width": 1440,
                "height": 960,
                "colorDepth": 24,
            },
            "timezone": "Europe/Berlin",
        }

    async def title(self) -> str:
        return "ChatGPT"


@pytest.mark.asyncio
async def test_collect_browser_snapshot_returns_current_page_state() -> None:
    snapshot = await collect_browser_snapshot(cast(Any, FakePage()))

    assert snapshot["url"] == "https://chatgpt.com/"
    assert snapshot["title"] == "ChatGPT"
    serialized = json.loads(json.dumps(snapshot))
    assert serialized["navigator"]["userAgent"] == "Mozilla/5.0"
    assert serialized["timezone"] == "Europe/Berlin"
