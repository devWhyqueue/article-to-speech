# Article to Speech

Docker-first Telegram automation that turns article URLs into full-article audio with Google Cloud Text-to-Speech and sends the result back to Telegram.

## What it does

- Accepts article URLs sent to a Telegram bot
- Resolves full article text from supported archive-backed publishers
- Synthesizes article audio with Google Cloud Text-to-Speech Chirp 3 HD voices
- Sends the final MP3 back to the same Telegram chat

## Required environment variables

Copy `.env.example` to `.env` and populate:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_ID`
- `GOOGLE_APPLICATION_CREDENTIALS`

Optional browser environment variables for archive rendering:

- `APP_RUNTIME_DIR` to move the runtime root (defaults to `.runtime/`)
- `BROWSER_HEADLESS` to force Playwright headless mode
- `BROWSER_LOCALE` to override the Playwright browser locale
- `BROWSER_TIMEZONE` to override the Playwright browser timezone
- `ARCHIVE_PROXY_URLS` and `ARCHIVE_PROXY_LIST_URL` for archive.is access

## Voice mapping

- `nytimes` uses `en-US-Chirp3-HD-Kore`
- `zeit`, `spiegel`, `sueddeutsche`, and `faz` use `de-DE-Chirp3-HD-Kore`

## Local development

Install `ffmpeg` on the host if you want to run `article-to-speech` outside Docker. On Ubuntu/WSL:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
```

```bash
uv sync --dev
uv run playwright install --with-deps chromium
uv run article-to-speech run-bot
```

One-shot processing:

```bash
uv run article-to-speech process-url "https://example.com/article"
```

## Docker usage

Place your service-account JSON at `./gcp-service-account.json`, then build and start the bot:

```bash
docker compose up --build app
```

Run one-shot processing inside Docker:

```bash
docker compose run --rm app process-url \
  "https://www.nytimes.com/2026/03/24/us/politics/supreme-court-trump-asylum-seekers.html"
```

## Runtime layout

By default runtime data lives in `.runtime/` locally and is mounted into `/data/` in Docker:

- `state/jobs.sqlite3` job state history
- `artifacts/` synthesized audio files
- `diagnostics/` browser-render diagnostics for archive extraction failures

## Deployment

Rebuild and restart only this app container on the server. Prefer image rebuilds over hot-patching a running container. Prune unused images occasionally to reclaim disk space.

## Troubleshooting

- If the Google credentials path is wrong or unreadable, synthesis fails before Telegram delivery.
- If Playwright cannot start Chromium locally, run `uv run playwright install --with-deps chromium`.
- If extraction fails, the bot sends a short error back to Telegram and records the failure in SQLite.

## Testing

```bash
uv run pytest
uv run pyright
uv run python /mnt/c/Users/yanni/.codex/skills/clean-code/run.py --minimal
```
