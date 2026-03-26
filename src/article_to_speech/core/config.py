from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from article_to_speech.core.exceptions import ConfigurationError


def _env_flag(values: dict[str, str], key: str, default: bool) -> bool:
    raw_value = values.get(key)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _env_text(values: dict[str, str], key: str) -> str | None:
    raw_value = values.get(key)
    if raw_value is None:
        return None
    value = raw_value.strip()
    return value or None


def _read_env_file(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        values[key.strip()] = raw_value.strip().strip('"').strip("'")
    return values


def _runtime_paths(base_dir: Path, values: dict[str, str]) -> tuple[Path, Path, Path, Path]:
    runtime_root = Path(values.get("APP_RUNTIME_DIR", base_dir / ".runtime")).expanduser()
    browser_profile_dir = runtime_root / "profile"
    state_dir = runtime_root / "state"
    artifacts_dir = runtime_root / "artifacts"
    diagnostics_dir = runtime_root / "diagnostics"
    for path in (browser_profile_dir, state_dir, artifacts_dir, diagnostics_dir):
        path.mkdir(parents=True, exist_ok=True)
    return runtime_root, browser_profile_dir, artifacts_dir, diagnostics_dir


def _required_values(values: dict[str, str]) -> tuple[str, int, str]:
    bot_token = _env_text(values, "TELEGRAM_BOT_TOKEN")
    allowed_chat_id = _env_text(values, "TELEGRAM_ALLOWED_CHAT_ID")
    project_name = _env_text(values, "CHATGPT_PROJECT_NAME")
    missing = [
        key
        for key, value in (
            ("TELEGRAM_BOT_TOKEN", bot_token),
            ("TELEGRAM_ALLOWED_CHAT_ID", allowed_chat_id),
            ("CHATGPT_PROJECT_NAME", project_name),
        )
        if value is None
    ]
    if missing:
        names = ", ".join(sorted(missing))
        raise ConfigurationError(f"Missing required environment variables: {names}")
    assert bot_token is not None
    assert allowed_chat_id is not None
    assert project_name is not None
    return (
        bot_token,
        int(allowed_chat_id),
        project_name,
    )


def _browser_runtime_settings(values: dict[str, str]) -> tuple[str | None, bool]:
    browser_display = values.get("DISPLAY")
    return (
        browser_display,
        _env_flag(
            values,
            "CHATGPT_BROWSER_HEADLESS",
            default=browser_display is None,
        ),
    )


def _default_browser_locale(values: dict[str, str]) -> str:
    raw_locale = _env_text(values, "CHATGPT_BROWSER_LOCALE") or _env_text(values, "LANG")
    if raw_locale is None:
        return "en-US"
    normalized = raw_locale.split(".", 1)[0]
    normalized = normalized.replace("_", "-")
    if normalized.lower() == "c":
        return "en-US"
    return normalized


def _default_browser_timezone(values: dict[str, str]) -> str | None:
    return _env_text(values, "CHATGPT_BROWSER_TIMEZONE") or _env_text(values, "TZ")


def _chatgpt_proxy_url(values: dict[str, str]) -> str | None:
    return _env_text(values, "CHATGPT_PROXY_URL")


def _chatgpt_project_url(values: dict[str, str]) -> str | None:
    return _env_text(values, "CHATGPT_PROJECT_URL")


def _archive_proxy_urls(values: dict[str, str]) -> tuple[str, ...]:
    raw_value = _env_text(values, "ARCHIVE_PROXY_URLS")
    if raw_value is None:
        return ()
    return tuple(item.strip() for item in raw_value.split(",") if item.strip())


def _archive_proxy_list_url(values: dict[str, str]) -> str | None:
    return _env_text(values, "ARCHIVE_PROXY_LIST_URL")


class SettingsKwargs(TypedDict):
    telegram_bot_token: str
    telegram_allowed_chat_id: int
    chatgpt_project_name: str
    runtime_root: Path
    browser_profile_dir: Path
    state_db_path: Path
    artifacts_dir: Path
    diagnostics_dir: Path
    browser_display: str | None
    chatgpt_browser_headless: bool
    browser_locale: str
    browser_timezone: str | None
    chatgpt_proxy_url: str | None
    chatgpt_project_url: str | None
    archive_proxy_urls: tuple[str, ...]
    archive_proxy_list_url: str | None


def _settings_kwargs(base_dir: Path) -> SettingsKwargs:
    values = {**_read_env_file(base_dir / ".env"), **os.environ}
    bot_token, allowed_chat_id, project_name = _required_values(values)
    runtime_root, browser_profile_dir, artifacts_dir, diagnostics_dir = _runtime_paths(
        base_dir,
        values,
    )
    browser_display, chatgpt_browser_headless = _browser_runtime_settings(values)
    return {
        "telegram_bot_token": bot_token,
        "telegram_allowed_chat_id": allowed_chat_id,
        "chatgpt_project_name": project_name,
        "runtime_root": runtime_root,
        "browser_profile_dir": browser_profile_dir,
        "state_db_path": runtime_root / "state" / "jobs.sqlite3",
        "artifacts_dir": artifacts_dir,
        "diagnostics_dir": diagnostics_dir,
        "browser_display": browser_display,
        "chatgpt_browser_headless": chatgpt_browser_headless,
        "browser_locale": _default_browser_locale(values),
        "browser_timezone": _default_browser_timezone(values),
        "chatgpt_proxy_url": _chatgpt_proxy_url(values),
        "chatgpt_project_url": _chatgpt_project_url(values),
        "archive_proxy_urls": _archive_proxy_urls(values),
        "archive_proxy_list_url": _archive_proxy_list_url(values),
    }


@dataclass(slots=True, frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_allowed_chat_id: int
    chatgpt_project_name: str
    runtime_root: Path
    browser_profile_dir: Path
    state_db_path: Path
    artifacts_dir: Path
    diagnostics_dir: Path
    browser_display: str | None
    chatgpt_browser_headless: bool
    browser_locale: str
    browser_timezone: str | None
    chatgpt_proxy_url: str | None
    chatgpt_project_url: str | None
    archive_proxy_urls: tuple[str, ...]
    archive_proxy_list_url: str | None
    http_user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    )
    article_timeout_seconds: float = 25.0
    article_retry_count: int = 3
    telegram_poll_timeout_seconds: int = 30
    min_article_word_count: int = 250

    @classmethod
    def load(cls, cwd: Path | None = None) -> Settings:
        """Load application settings from `.env` and process environment variables."""
        base_dir = cwd or Path.cwd()
        return cls(**_settings_kwargs(base_dir))
