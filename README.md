# Article to Speech

Docker-first Telegram automation that turns article URLs into full-article audio by routing the text through the real ChatGPT website and returning the resulting narration back to Telegram.

## What it does

- Accepts article URLs sent to a Telegram bot
- Resolves full article text with direct fetch, structured-data extraction, and a single browser-rendered fallback
- Uses a persistent ChatGPT browser profile stored on disk
- Opens or reuses the `Articles` project in the ChatGPT web app
- Triggers browser-side read-aloud and captures the resulting audio
- Sends the final audio file back to the same Telegram chat

## Required environment variables

Copy `.env.example` to `.env` and populate:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_ID`
- `CHATGPT_PROJECT_NAME`

`CHATGPT_PROJECT_NAME` should remain `Articles`.

Optional browser environment variables:

- `APP_RUNTIME_DIR` to move the shared runtime root (defaults to `.runtime/`)
- `CHATGPT_BROWSER_LOCALE` to override the Playwright browser locale
- `CHATGPT_BROWSER_TIMEZONE` to override the Playwright browser timezone

## Local development

```bash
uv sync --dev
uv run article-to-speech run-bot
```

One-shot processing:

```bash
uv run article-to-speech process-url "https://example.com/article"
```

Preferred ChatGPT bootstrap flow on WSLg:

```bash
uv run playwright install --with-deps chromium
uv run article-to-speech setup-browser
```

That local headed Linux browser writes into `.runtime/profile`, which is the same runtime directory Docker mounts later. This is the recommended login path when Cloudflare loops inside the container desktop.

## Docker usage

Build and start the bot:

```bash
docker compose up --build app
```

The compose services bind-mount `./.runtime` into `/data`, so local bootstrap and Docker automation reuse the same ChatGPT profile, state database, artifacts, and diagnostics.

Fallback container bootstrap through noVNC:

```bash
docker compose up --build setup-browser
```

Then open [http://localhost:6080/vnc.html](http://localhost:6080/vnc.html), complete ChatGPT login and any 2FA, and leave `.runtime/` in place for normal runs. This path is mainly for debugging because Cloudflare is more likely to challenge the Docker browser desktop than the local WSLg bootstrap.

If `setup-browser` is running on a remote server, prefer an SSH local port-forward instead of exposing noVNC publicly.

Linux / WSL:

```bash
ssh -L 6080:localhost:6080 ubuntu@89.168.90.195
```

Windows:

```powershell
ssh -L 6080:localhost:6080 ubuntu@89.168.90.195 -i C:\Users\yanni\.ssh\ssh-key-2023-09-20.key
```

Keep that SSH session open, then browse to [http://localhost:6080/vnc.html](http://localhost:6080/vnc.html) locally. This keeps noVNC off the public internet and does not require nginx changes. If the compose port mapping is later restricted to `127.0.0.1`, the SSH tunnel still works and is the safer server setup.

If you need to force headless mode for debugging outside Docker, set `CHATGPT_BROWSER_HEADLESS=true`.

Run one-shot processing inside Docker:

```bash
docker compose run --rm app process-url \
  "https://www.nytimes.com/2026/03/24/us/politics/supreme-court-trump-asylum-seekers.html"
```

## Runtime layout

By default runtime data lives in `.runtime/` locally and is mounted into `/data/` in Docker:

- `profile/` persistent ChatGPT browser profile
- `state/jobs.sqlite3` job state history
- `artifacts/` captured audio files
- `diagnostics/` screenshots, HTML dumps, and browser step logs

## Troubleshooting

- If ChatGPT redirects to login, rerun the browser setup flow and re-authenticate in the persistent profile.
- Browser failures and setup-browser challenge loops write screenshots, HTML, browser snapshots, and step logs into the diagnostics directory.
- If local WSLg bootstrap cannot start Chromium, install the Linux runtime dependencies with `uv run playwright install --with-deps chromium`.
- If extraction fails, the bot sends a short error back to Telegram and records the failure in SQLite.
- No progress messages are sent to Telegram during normal processing.

## Testing

```bash
uv run pytest
uv run pyright
uv run python /mnt/c/Users/yanni/.codex/skills/clean-code/run.py --minimal
```
