from __future__ import annotations

import json
from typing import Any, cast

import pytest

from article_to_speech.browser.capture import collect_browser_snapshot
from article_to_speech.browser.launch import (
    browser_args,
    build_browser_context_options,
    normalize_profile_shutdown_state,
    setup_browser_args,
)
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


def test_build_browser_context_options_keep_existing_args_and_include_user_agent(
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
    assert options["user_agent"] == settings.http_user_agent
    assert args == browser_args()
    assert "--disable-blink-features=AutomationControlled" in args
    assert "--start-maximized" in args
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


def test_build_browser_context_options_include_proxy_override(tmp_path) -> None:
    _write_env_file(tmp_path, "CHATGPT_PROXY_URL=http://user:pass@proxy.example:8080")

    settings = Settings.load(tmp_path)
    options = build_browser_context_options(settings)

    assert options.get("proxy") == {
        "server": "http://proxy.example:8080",
        "username": "user",
        "password": "pass",
    }


def test_browser_args_hide_crash_restore_bubble() -> None:
    args = browser_args()

    assert "--disable-session-crashed-bubble" in args
    assert "--hide-crash-restore-bubble" in args


def test_setup_browser_args_launch_manual_profile_window(tmp_path) -> None:
    args = setup_browser_args(tmp_path / "profile", "https://chatgpt.com/")

    assert "--disable-gpu" in args
    assert f"--user-data-dir={tmp_path / 'profile'}" in args
    assert "--disable-setuid-sandbox" in args
    assert "--new-window" in args
    assert "--no-first-run" in args
    assert "--no-sandbox" in args
    assert "--disable-software-rasterizer" in args
    assert args[-1] == "https://chatgpt.com/"


def test_normalize_profile_shutdown_state_marks_profile_clean(tmp_path) -> None:
    preferences_path = tmp_path / "Default" / "Preferences"
    local_state_path = tmp_path / "Local State"
    preferences_path.parent.mkdir(parents=True)
    preferences_path.write_text(
        json.dumps({"exit_type": "Crashed", "exited_cleanly": False}),
        encoding="utf-8",
    )
    local_state_path.write_text(
        json.dumps({"exit_type": "Crashed", "exited_cleanly": False}),
        encoding="utf-8",
    )

    normalize_profile_shutdown_state(tmp_path)

    assert json.loads(preferences_path.read_text(encoding="utf-8")) == {
        "exit_type": "Normal",
        "exited_cleanly": True,
    }
    assert json.loads(local_state_path.read_text(encoding="utf-8")) == {
        "exit_type": "Normal",
        "exited_cleanly": True,
    }


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
