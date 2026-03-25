from __future__ import annotations

import argparse
import asyncio

from article_to_speech.core.config import Settings
from article_to_speech.core.logging_config import configure_logging
from article_to_speech.service import run_bot, run_process_url, run_setup_browser


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Telegram article-to-audio automation.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("run-bot", help="Run the Telegram long-polling bot.")
    subparsers.add_parser("setup-browser", help="Open ChatGPT in the persistent browser profile.")

    process_parser = subparsers.add_parser(
        "process-url", help="Process a single URL and send audio to Telegram."
    )
    process_parser.add_argument("url")
    process_parser.add_argument("--chat-id", type=int)
    return parser


def main() -> int:
    """Run the selected CLI command."""
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()
    settings = Settings.load()

    if args.command == "run-bot":
        asyncio.run(run_bot(settings))
        return 0
    if args.command == "setup-browser":
        asyncio.run(run_setup_browser(settings))
        return 0
    if args.command == "process-url":
        return asyncio.run(run_process_url(settings, args))
    parser.error(f"Unsupported command: {args.command}")
    return 2
