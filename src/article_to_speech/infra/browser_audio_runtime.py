from __future__ import annotations

from typing import cast

from playwright.async_api import Error, Page


async def _extract_audio_segments_from_page(page: Page) -> list[dict[str, str]]:
    for _ in range(20):
        try:
            result = await page.evaluate(
                """
                async () => {
                    const state = window.__atsAudioState || { sources: [] };
                    const audioElements = Array.from(document.querySelectorAll("audio"));
                    const sourceUrls = [];
                    const seen = new Set();
                    const candidates = [
                        ...state.sources.map((entry) => entry?.src || ""),
                        ...audioElements.flatMap((audio) => [audio.currentSrc || "", audio.src || ""]),
                    ];
                    for (const candidate of candidates) {
                        if (!candidate || seen.has(candidate)) {
                            continue;
                        }
                        seen.add(candidate);
                        sourceUrls.push(candidate);
                    }
                    if (!sourceUrls.length) {
                        return [];
                    }
                    const segments = [];
                    for (const url of sourceUrls) {
                        const response = await fetch(url);
                        const buffer = await response.arrayBuffer();
                        const bytes = new Uint8Array(buffer);
                        let binary = "";
                        for (const value of bytes) {
                            binary += String.fromCharCode(value);
                        }
                        const format = url.includes(".mp3")
                            ? "mp3"
                            : url.includes(".m4a")
                              ? "m4a"
                              : "webm";
                        segments.push({ mode: "bytes", payload: btoa(binary), format, url });
                    }
                    return segments;
                }
                """
            )
        except Error:
            result = []
        if result:
            return cast(list[dict[str, str]], result)
        await page.wait_for_timeout(1_000)
    return []


async def _record_audio_stream(page: Page) -> str | None:
    for _ in range(15):
        recorded = await page.evaluate(
            """
            async () => {
                const audio = document.querySelector("audio");
                if (!audio || typeof audio.captureStream !== "function") {
                    return null;
                }
                const stream = audio.captureStream();
                const recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
                const chunks = [];
                return await new Promise((resolve) => {
                    recorder.ondataavailable = (event) => {
                        if (event.data.size) {
                            chunks.push(event.data);
                        }
                    };
                    recorder.onstop = async () => {
                        const blob = new Blob(chunks, { type: "audio/webm" });
                        const buffer = await blob.arrayBuffer();
                        const bytes = new Uint8Array(buffer);
                        let binary = "";
                        for (const value of bytes) {
                            binary += String.fromCharCode(value);
                        }
                        resolve(btoa(binary));
                    };
                    const stopRecording = () => {
                        if (recorder.state !== "inactive") {
                            recorder.stop();
                        }
                    };
                    audio.addEventListener("ended", stopRecording, { once: true });
                    recorder.start();
                    if (audio.paused) {
                        audio.play().catch(() => {});
                    }
                    setTimeout(stopRecording, 3600000);
                });
            }
            """
        )
        if isinstance(recorded, str) and recorded:
            return recorded
        await page.wait_for_timeout(1_000)
    return None


async def _wait_for_audio_completion(
    page: Page,
    response_payloads: list[tuple[str, str, bytes]],
    downloads: list[object],
    *,
    timeout_ms: int = 1_800_000,
    settle_ms: int = 4_000,
    startup_timeout_ms: int = 20_000,
) -> None:
    start_state = await _audio_observation(page)
    previous_activity = _activity_marker(start_state, response_payloads, downloads)
    deadline = timeout_ms
    waited_ms = 0
    stable_for_ms = 0
    while deadline > 0:
        await page.wait_for_timeout(500)
        deadline -= 500
        waited_ms += 500
        current_state = await _audio_observation(page)
        activity = _activity_marker(current_state, response_payloads, downloads)
        has_started = (
            activity["source_count"] > 0
            or activity["payload_count"] > 0
            or activity["download_count"] > 0
        )
        if not has_started and waited_ms >= startup_timeout_ms:
            return
        if activity != previous_activity:
            stable_for_ms = 0
            previous_activity = activity
            continue
        stable_for_ms += 500
        if has_started and activity["playing_count"] == 0 and stable_for_ms >= settle_ms:
            return


async def _audio_observation(page: Page) -> dict[str, int]:
    observation = await page.evaluate(
        """
        () => {
            const state = window.__atsAudioState || { sources: [] };
            const audioElements = Array.from(document.querySelectorAll("audio"));
            const playingCount = audioElements.filter(
                (audio) => !audio.paused && !audio.ended
            ).length;
            return {
                sourceCount: state.sources.length,
                playingCount,
            };
        }
        """
    )
    return cast(dict[str, int], observation)


def _activity_marker(
    observation: dict[str, int],
    response_payloads: list[tuple[str, str, bytes]],
    downloads: list[object],
) -> dict[str, int]:
    return {
        "source_count": int(observation.get("sourceCount", 0)),
        "playing_count": int(observation.get("playingCount", 0)),
        "payload_count": len(response_payloads),
        "download_count": len(downloads),
    }
