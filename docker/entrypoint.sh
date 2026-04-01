#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run-bot}"
shift || true

case "$MODE" in
  run-bot|process-url)
    exec uv run article-to-speech "$MODE" "$@"
    ;;
  *)
    echo "Unknown mode: $MODE" >&2
    exit 2
    ;;
esac
