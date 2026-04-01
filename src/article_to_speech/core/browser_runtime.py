from __future__ import annotations


def browser_args() -> list[str]:
    """Return Chromium flags for archive rendering."""
    return [
        "--autoplay-policy=no-user-gesture-required",
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--disable-features=IsolateOrigins,site-per-process",
        "--disable-gpu",
        "--disable-session-crashed-bubble",
        "--disable-setuid-sandbox",
        "--disable-software-rasterizer",
        "--hide-crash-restore-bubble",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-sandbox",
        "--start-maximized",
    ]
