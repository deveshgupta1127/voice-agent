import asyncio
import base64
import logging
import struct
import time
from typing import Awaitable, Callable

from sarvamai import AsyncSarvamAI

logger = logging.getLogger("voice_agent.tts")


def _wav_header(data_len: int, channels: int, sampwidth: int, framerate: int) -> bytes:
    """Build a 44-byte WAV header for `data_len` bytes of raw PCM."""
    byte_rate = framerate * channels * sampwidth
    block_align = channels * sampwidth
    return (
        b"RIFF"
        + struct.pack("<I", 36 + data_len)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, framerate, byte_rate, block_align, sampwidth * 8)
        + b"data"
        + struct.pack("<I", data_len)
    )


class SarvamTTS:
    """Streaming Sarvam Bulbul TTS over a single persistent WebSocket.

    The socket is opened once per session (the handshake is ~1s, so it must be
    reused). Sarvam streams a 44-byte WAV header followed by raw PCM; we
    re-wrap the PCM into small complete WAV blobs so the browser can play each
    as it arrives (first audio in ~100-300ms instead of ~2s for batch).
    """

    def __init__(self, api_key: str, model: str = "bulbul:v3",
                 target_language: str = "en-IN", speaker: str = "shubh"):
        self._client = AsyncSarvamAI(api_subscription_key=api_key)
        self._model = model
        self._default_lang = target_language
        self._speaker = speaker

        self._cm = None
        self._ws = None
        self._configured_lang: str | None = None
        self._connect_lock = asyncio.Lock()

        # PCM format learned from the streamed WAV header.
        self._channels = 1
        self._sampwidth = 2
        self._framerate = 22050

        # True while a convert() is in flight; if a turn is cancelled (barge-in)
        # mid-synthesis, the next call drains the leftover stream first.
        self._dirty = False

        # Background task that makes the socket connected+clean before the next
        # synthesis, so the handshake/drain never lands on the hot path.
        self._prewarm_task: asyncio.Task | None = None

    async def connect(self) -> None:
        async with self._connect_lock:
            if self._ws is not None:
                return
            self._cm = self._client.text_to_speech_streaming.connect(
                model=self._model, send_completion_event="true"
            )
            self._ws = await self._cm.__aenter__()
            await self._ws.configure(
                target_language_code=self._default_lang,
                speaker=self._speaker,
                output_audio_codec="wav",
            )
            self._configured_lang = self._default_lang
            logger.info("TTS streaming socket connected")

    def prewarm(self) -> None:
        """Schedule socket readiness in the background.

        Call this at the START of a user turn (the moment they stop speaking).
        Any handshake / post-barge-in drain / reconnect then overlaps STT + LLM
        — which always run before the first sentence reaches TTS — so the hot
        path pays ~0ms instead of a ~1.2s handshake.
        """
        if self._prewarm_task is not None and not self._prewarm_task.done():
            return
        self._prewarm_task = asyncio.create_task(self._do_prewarm())

    async def _do_prewarm(self) -> float:
        """Make the socket connected and clean. Returns ms spent (for metrics)."""
        t = time.monotonic()
        try:
            if self._ws is None:
                await self.connect()
            elif self._dirty:
                if not await self._drain_until_final(budget_s=0.8):
                    await self._reconnect()
        except Exception as e:
            logger.warning("TTS pre-warm failed: %s", e)
        return (time.monotonic() - t) * 1000

    async def synthesize_stream(
        self,
        text: str,
        target_language: str | None,
        on_wav: Callable[[bytes], Awaitable[None]],
    ) -> dict:
        """Synthesize `text`, calling on_wav(wav_bytes) for each playable WAV
        chunk as audio streams in. Returns a stats dict so the caller can see
        exactly where the time went:
            ttfb_ms     - convert() -> first audio chunk (pure TTS responsiveness)
            synth_ms    - convert() -> done (whole sentence, incl. browser send)
            emit_ms     - time awaiting on_wav (pushing audio to the browser)
            recovery_ms - socket warm/reconnect paid on the hot path (~0 if pre-warmed)
            stalled     - True if the provider stalled and audio was abandoned
        """
        recovery_ms = 0.0

        # Let any background pre-warm finish. Only the time we actually WAIT here
        # is hot-path cost: if pre-warm already completed during this turn's
        # STT + LLM, the await returns instantly and recovery stays ~0. The
        # handshake/drain itself ran off the hot path.
        if self._prewarm_task is not None:
            t = time.monotonic()
            try:
                await self._prewarm_task
            except Exception:
                pass
            recovery_ms += (time.monotonic() - t) * 1000
            self._prewarm_task = None

        if self._ws is None:
            t = time.monotonic()
            await self.connect()
            recovery_ms += (time.monotonic() - t) * 1000

        if self._dirty:
            # Pre-warm wasn't called or didn't finish cleaning — recover inline.
            t = time.monotonic()
            if not await self._drain_until_final(budget_s=0.8):
                await self._reconnect()
            recovery_ms += (time.monotonic() - t) * 1000

        lang = target_language or self._default_lang
        if lang != self._configured_lang:
            try:
                await self._ws.configure(
                    target_language_code=lang,
                    speaker=self._speaker,
                    output_audio_codec="wav",
                )
                self._configured_lang = lang
            except Exception as e:
                logger.warning("TTS reconfigure to %s failed: %s", lang, e)

        convert_t = time.monotonic()
        await self._ws.convert(text)
        await self._ws.flush()
        self._dirty = True

        pcm_buf = bytearray()
        first_emitted = False
        ttfb_ms: float | None = None
        emit_ms = 0.0
        stalled = False

        async def emit(force: bool = False):
            nonlocal first_emitted, emit_ms
            # Emit the first chunk the instant any audio is ready (low first-audio
            # latency), then batch ~0.35s per chunk so sequential playback stays smooth.
            target = int(self._framerate * self._sampwidth * self._channels * 0.35)
            if pcm_buf and (force or not first_emitted or len(pcm_buf) >= target):
                wav = _wav_header(len(pcm_buf), self._channels, self._sampwidth, self._framerate) + bytes(pcm_buf)
                e0 = time.monotonic()
                await on_wav(wav)
                emit_ms += (time.monotonic() - e0) * 1000
                pcm_buf.clear()
                first_emitted = True

        while True:
            try:
                # No chunk in 12s => provider stalled/throttled; don't hang the turn.
                msg = await asyncio.wait_for(self._ws.recv(), timeout=12)
            except asyncio.TimeoutError:
                logger.warning("TTS stream stalled (>12s, likely Sarvam throttling) — abandoning audio for this reply")
                await emit(force=True)
                self._dirty = True  # next reply will drain/reconnect the socket
                stalled = True
                break
            cls = type(msg).__name__
            if cls == "AudioOutput":
                raw = self._extract_pcm(msg)
                if raw:
                    if ttfb_ms is None:
                        ttfb_ms = (time.monotonic() - convert_t) * 1000
                    pcm_buf.extend(raw)
                    await emit()
            elif cls == "EventResponse":
                if getattr(getattr(msg, "data", None), "event_type", None) == "final":
                    await emit(force=True)
                    self._dirty = False
                    break
            elif cls == "ErrorResponse":
                logger.error("TTS error: %s", getattr(msg, "data", msg))
                await emit(force=True)
                self._dirty = False
                break

        return {
            "ttfb_ms": ttfb_ms,
            "synth_ms": (time.monotonic() - convert_t) * 1000,
            "emit_ms": emit_ms,
            "recovery_ms": recovery_ms,
            "stalled": stalled,
        }

    def _extract_pcm(self, msg) -> bytes:
        data = getattr(msg, "data", None)
        audio_b64 = getattr(data, "audio", None) if data is not None else None
        if not audio_b64:
            return b""
        raw = base64.b64decode(audio_b64)
        if raw[:4] == b"RIFF" and len(raw) >= 44:
            self._parse_header(raw[:44])
            raw = raw[44:]
        return raw

    def _parse_header(self, hdr: bytes) -> None:
        try:
            self._channels = struct.unpack("<H", hdr[22:24])[0] or 1
            self._framerate = struct.unpack("<I", hdr[24:28])[0] or 22050
            self._sampwidth = (struct.unpack("<H", hdr[34:36])[0] or 16) // 8
        except Exception:
            pass

    async def _drain_until_final(self, budget_s: float = 1.0) -> bool:
        """Consume a cancelled convert's leftover stream so the socket is clean.

        Returns True if it reached the 'final' event within the time budget,
        False if it should be reconnected instead.
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + budget_s
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return False
                msg = await asyncio.wait_for(self._ws.recv(), timeout=remaining)
                if type(msg).__name__ == "EventResponse" and \
                        getattr(getattr(msg, "data", None), "event_type", None) == "final":
                    self._dirty = False
                    return True
        except Exception:
            return False

    async def _reconnect(self) -> None:
        await self.close()
        self._dirty = False
        self._configured_lang = None
        await self.connect()

    async def close(self) -> None:
        if self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception:
                pass
            self._cm = None
            self._ws = None
