from __future__ import annotations

from pathlib import Path

import pytest

from article_to_speech.core.exceptions import ConfigurationError
from article_to_speech.core.config import Settings


def test_settings_use_headed_browser_when_display_is_available(tmp_path, monkeypatch) -> None:
    credentials_path = tmp_path / "service-account.json"
    credentials_path.write_text("{}", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_CHAT_ID=123",
                f"GOOGLE_APPLICATION_CREDENTIALS={credentials_path}",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.delenv("BROWSER_TIMEZONE", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    settings = Settings.load(tmp_path)

    assert settings.browser_headless is False
    assert settings.browser_locale == "en-US"
    assert settings.browser_timezone is None
    assert settings.google_application_credentials == credentials_path


def test_settings_allow_explicit_headless_override(tmp_path, monkeypatch) -> None:
    credentials_path = tmp_path / "service-account.json"
    credentials_path.write_text("{}", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_CHAT_ID=123",
                f"GOOGLE_APPLICATION_CREDENTIALS={credentials_path}",
                "BROWSER_HEADLESS=true",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DISPLAY", ":99")

    settings = Settings.load(tmp_path)

    assert settings.browser_headless is True


def test_settings_allow_browser_locale_and_timezone_overrides(tmp_path) -> None:
    credentials_path = tmp_path / "service-account.json"
    credentials_path.write_text("{}", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_CHAT_ID=123",
                f"GOOGLE_APPLICATION_CREDENTIALS={credentials_path}",
                "BROWSER_LOCALE=de-DE",
                "BROWSER_TIMEZONE=Europe/Berlin",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.browser_locale == "de-DE"
    assert settings.browser_timezone == "Europe/Berlin"


def test_settings_trim_required_values_from_environment(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    credentials_path = tmp_path / "service-account.json"
    credentials_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", " test-token\r\n")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_ID", " 123 \r\n")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", f" {credentials_path} \r\n")

    settings = Settings.load(tmp_path)

    assert settings.telegram_bot_token == "test-token"
    assert settings.telegram_allowed_chat_id == 123
    assert settings.google_application_credentials == credentials_path


def test_settings_parse_archive_proxy_urls(tmp_path) -> None:
    credentials_path = tmp_path / "service-account.json"
    credentials_path.write_text("{}", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_CHAT_ID=123",
                f"GOOGLE_APPLICATION_CREDENTIALS={credentials_path}",
                "ARCHIVE_PROXY_URLS=http://u1:p1@one:1111, http://u2:p2@two:2222",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.archive_proxy_urls == (
        "http://u1:p1@one:1111",
        "http://u2:p2@two:2222",
    )


def test_settings_parse_archive_proxy_list_url(tmp_path, monkeypatch) -> None:
    credentials_path = tmp_path / "service-account.json"
    credentials_path.write_text("{}", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_CHAT_ID=123",
                f"GOOGLE_APPLICATION_CREDENTIALS={credentials_path}",
                "ARCHIVE_PROXY_LIST_URL=https://proxy.example/list.txt",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("ARCHIVE_PROXY_LIST_URL", raising=False)

    settings = Settings.load(tmp_path)

    assert settings.archive_proxy_list_url == "https://proxy.example/list.txt"


def test_settings_reject_missing_google_credentials_env_var(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_CHAT_ID=123",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    with pytest.raises(ConfigurationError, match="GOOGLE_APPLICATION_CREDENTIALS"):
        Settings.load(tmp_path)


def test_settings_expand_google_credentials_path(tmp_path, monkeypatch) -> None:
    credentials_path = Path.home() / "service-account.json"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_ID", "123")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "~/service-account.json")

    settings = Settings.load(tmp_path)

    assert settings.google_application_credentials == credentials_path
