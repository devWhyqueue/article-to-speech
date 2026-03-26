from __future__ import annotations

from typing import cast

from playwright.async_api import Error, Page


async def _extract_audio_sources_from_page(
    page: Page, *, retries: int = 20
) -> list[dict[str, str]]:
    for _ in range(retries):
        try:
            result = await page.evaluate(
                """
                () => {
                    const state = window.__atsAudioState || { sources: [], events: [] };
                    const audioElements = Array.from(document.querySelectorAll("audio"));
                    const sourceUrls = [];
                    const seen = new Set();
                    const candidates = [
                        ...state.sources.map((entry) => entry?.src || ""),
                        ...state.events.map((entry) => entry?.src || ""),
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
                    const sources = [];
                    for (const url of sourceUrls) {
                        const format = url.includes(".mp3")
                            ? "mp3"
                            : url.includes(".m4a")
                              ? "m4a"
                              : "webm";
                        sources.push({ format, url });
                    }
                    return sources;
                }
                """
            )
        except Error:
            result = []
        if result:
            return cast(list[dict[str, str]], result)
        await page.wait_for_timeout(1_000)
    return []


async def _record_played_audio_blob(page: Page, timeout_ms: int = 120_000) -> str | None:
    try:
        await page.evaluate(
            """
            () => {
                const audio = document.querySelector("audio");
                if (!audio || typeof audio.captureStream !== "function") {
                    window.__atsBlobRecorder = { state: "missing" };
                    return;
                }
                if (window.__atsBlobRecorder?.state === "recording") {
                    return;
                }
                const stream = audio.captureStream();
                const recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
                const chunks = [];
                window.__atsBlobRecorder = { state: "recording", payload: null, error: null };
                recorder.ondataavailable = (event) => {
                    if (event.data.size) {
                        chunks.push(event.data);
                    }
                };
                recorder.onerror = (event) => {
                    window.__atsBlobRecorder = {
                        state: "error",
                        payload: null,
                        error: String(event.error || "media-recorder-error"),
                    };
                };
                recorder.onstop = async () => {
                    try {
                        const blob = new Blob(chunks, { type: "audio/webm" });
                        const buffer = await blob.arrayBuffer();
                        const bytes = new Uint8Array(buffer);
                        let binary = "";
                        for (const value of bytes) {
                            binary += String.fromCharCode(value);
                        }
                        window.__atsBlobRecorder = {
                            state: "done",
                            payload: btoa(binary),
                            error: null,
                        };
                    } catch (error) {
                        window.__atsBlobRecorder = {
                            state: "error",
                            payload: null,
                            error: String(error),
                        };
                    }
                };
                const stopRecording = () => {
                    if (recorder.state !== "inactive") {
                        recorder.stop();
                    }
                };
                audio.addEventListener("ended", stopRecording, { once: true });
                recorder.start();
            }
            """
        )
    except Error:
        return None
    waited_ms = 0
    while waited_ms < timeout_ms:
        try:
            recorder_state = await page.evaluate(
                """
                () => window.__atsBlobRecorder || { state: "missing", payload: null, error: null }
                """
            )
        except Error:
            return None
        state = str(recorder_state.get("state", "missing"))
        if state == "done":
            payload = recorder_state.get("payload")
            return payload if isinstance(payload, str) and payload else None
        if state in {"missing", "error"}:
            return None
        await page.wait_for_timeout(1_000)
        waited_ms += 1_000
    return None
