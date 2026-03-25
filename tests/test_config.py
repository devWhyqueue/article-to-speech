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


def test_settings_trim_required_values_from_environment(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", " test-token\r\n")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_ID", " 123 \r\n")
    monkeypatch.setenv("CHATGPT_PROJECT_NAME", " Articles \r\n")

    settings = Settings.load(tmp_path)

    assert settings.telegram_bot_token == "test-token"
    assert settings.telegram_allowed_chat_id == 123
    assert settings.chatgpt_project_name == "Articles"


def test_settings_parse_archive_proxy_urls(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_CHAT_ID=123",
                "CHATGPT_PROJECT_NAME=Articles",
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
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_CHAT_ID=123",
                "CHATGPT_PROJECT_NAME=Articles",
                "ARCHIVE_PROXY_LIST_URL=https://proxy.example/list.txt",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("ARCHIVE_PROXY_LIST_URL", raising=False)

    settings = Settings.load(tmp_path)

    assert settings.archive_proxy_list_url == "https://proxy.example/list.txt"


def test_settings_parse_chatgpt_proxy_url(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_CHAT_ID=123",
                "CHATGPT_PROJECT_NAME=Articles",
                "CHATGPT_PROXY_URL=http://user:pass@proxy.example:8080",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.chatgpt_proxy_url == "http://user:pass@proxy.example:8080"


def test_settings_parse_chatgpt_project_url(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_CHAT_ID=123",
                "CHATGPT_PROJECT_NAME=Articles",
                "CHATGPT_PROJECT_URL=https://chatgpt.com/g/g-p-example-articles/project",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.chatgpt_project_url == "https://chatgpt.com/g/g-p-example-articles/project"
