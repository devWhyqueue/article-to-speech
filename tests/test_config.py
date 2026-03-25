from __future__ import annotations

from article_to_speech.core.config import Settings


def test_settings_use_headed_browser_when_display_is_available(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_CHAT_ID=123",
                "CHATGPT_PROJECT_NAME=Articles",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DISPLAY", ":99")

    settings = Settings.load(tmp_path)

    assert settings.browser_display == ":99"
    assert settings.chatgpt_browser_headless is False
    assert settings.browser_locale == "en-US"
    assert settings.browser_timezone is None


def test_settings_allow_explicit_headless_override(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_CHAT_ID=123",
                "CHATGPT_PROJECT_NAME=Articles",
                "CHATGPT_BROWSER_HEADLESS=true",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DISPLAY", ":99")

    settings = Settings.load(tmp_path)

    assert settings.chatgpt_browser_headless is True


def test_settings_allow_browser_locale_and_timezone_overrides(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_CHAT_ID=123",
                "CHATGPT_PROJECT_NAME=Articles",
                "CHATGPT_BROWSER_LOCALE=de-DE",
                "CHATGPT_BROWSER_TIMEZONE=Europe/Berlin",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.browser_locale == "de-DE"
    assert settings.browser_timezone == "Europe/Berlin"
