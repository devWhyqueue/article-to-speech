#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run-bot}"
shift || true

run_uv() {
  exec uv run article-to-speech "$MODE" "$@"
}

cleanup() {
  for pid in "${BACKGROUND_PIDS[@]:-}"; do
    kill "$pid" >/dev/null 2>&1 || true
  done
}

start_virtual_display() {
  if [[ -n "${DISPLAY:-}" ]]; then
    return
  fi
  export DISPLAY=:99
  Xvfb "$DISPLAY" -screen 0 1600x900x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
  BACKGROUND_PIDS+=("$!")
  wait_for_display
}

wait_for_display() {
  local display_number="${DISPLAY#:}"
  local socket_path="/tmp/.X11-unix/X${display_number}"
  for _ in $(seq 1 50); do
    if [[ -S "$socket_path" ]]; then
      return
    fi
    sleep 0.1
  done
  echo "Xvfb did not become ready on ${DISPLAY}" >&2
  exit 1
}

start_novnc_stack() {
  fluxbox >/tmp/fluxbox.log 2>&1 &
  BACKGROUND_PIDS+=("$!")
  x11vnc -display "$DISPLAY" -forever -shared -nopw -rfbport 5900 >/tmp/x11vnc.log 2>&1 &
  BACKGROUND_PIDS+=("$!")
  websockify --web=/usr/share/novnc/ 6080 localhost:5900 >/tmp/websockify.log 2>&1 &
  BACKGROUND_PIDS+=("$!")
}

declare -a BACKGROUND_PIDS=()
trap cleanup EXIT

case "$MODE" in
  run-bot|process-url|setup-browser)
    start_virtual_display
    run_uv "$@"
    ;;
  setup-browser-desktop)
    start_virtual_display
    start_novnc_stack
    uv run article-to-speech setup-browser "$@"
    ;;
  *)
    echo "Unknown mode: $MODE" >&2
    exit 2
    ;;
esac
