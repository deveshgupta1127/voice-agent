import asyncio
import base64
import io
import logging
import time
import wave
from concurrent.futures import ThreadPoolExecutor

from sarvamai import SarvamAI, AsyncSarvamAI

logger = logging.getLogger("voice_agent.stt")

_executor = ThreadPoolExecutor(max_workers=2)


class SarvamSTT:
    """Sarvam Saaras STT with a streaming-first / batch-fallback design.

    Audio chunks are forwarded to a persistent streaming socket *as they arrive*
    (so the transcript is ready almost instantly on stop), AND buffered for a
    batch transcription fallback. If streaming is disabled, fails to connect,
    errors, or yields nothing, we transparently fall back to the batch call —
    so this can never be slower or less reliable than the original batch path.
    Set STT_STREAMING=false to force batch.
    """

    def __init__(self, api_key: str, model: str = "saaras:v3", language: str = "unknown",
                 mode: str = "transcribe", sample_rate: int = 16000, streaming: bool = True):
        self._client = SarvamAI(api_subscription_key=api_key)            # batch
        self._async_client = AsyncSarvamAI(api_subscription_key=api_key)  # streaming
        self._model = model
        self._language = language
        self._mode = mode
        self._sample_rate = sample_rate
        self._streaming_enabled = streaming

        self._audio_chunks: list[bytes] = []   # batch fallback buffer

        # streaming state
        self._cm = None
        self._ws = None
        self._receiver: asyncio.Task | None = None
        self._stream_alive = False
        self._sent_any = False
        # Accumulate VAD-split speech segments (e.g. spoken digits) for one
        # utterance instead of overwriting.
        self._committed: list[str] = []   # finalized segments this utterance
        self._current = ""                # active segment's latest transcript
        self._latest_language: str | None = None

    async def connect_stream(self) -> None:
        if not self._streaming_enabled:
            return
        try:
            self._cm = self._async_client.speech_to_text_streaming.connect(
                language_code="unknown",
                model=self._model,
                mode=self._mode,
                high_vad_sensitivity="true",
                input_audio_codec="pcm_s16le",
                sample_rate=str(self._sample_rate),
            )
            self._ws = await self._cm.__aenter__()
            self._receiver = asyncio.create_task(self._receive_loop())
            self._stream_alive = True
            logger.info("STT streaming socket connected")
        except Exception as e:
            logger.warning("STT streaming connect failed, using batch: %s", e)
            self._stream_alive = False

    async def _receive_loop(self) -> None:
        try:
            while True:
                msg = await self._ws.recv()
                if getattr(msg, "type", None) == "data" and getattr(msg, "data", None) is not None:
                    data = msg.data
                    t = (getattr(data, "transcript", None) or "").strip()
                    if t:
                        logger.info("STT raw-seg: %r", t)  # diagnostic: what Sarvam streams
                        self._add_segment_text(t)
                    lc = getattr(data, "language_code", None)
                    if lc:
                        self._latest_language = lc
        except Exception as e:
            logger.warning("STT receiver ended (falling back to batch): %s", e)
            self._stream_alive = False

    def _add_segment_text(self, t: str) -> None:
        # A segment's transcript arrives as a growing partial then a final (same
        # text), so anything that overlaps the current segment just replaces it
        # (no duplicate). Only genuinely non-overlapping text (the next spoken
        # digit/word) starts a new segment.
        if self._current == "" or t.startswith(self._current):
            self._current = t
        elif self._current.startswith(t):
            return
        else:
            self._committed.append(self._current)
            self._current = t

    def _full_transcript(self) -> str:
        parts = self._committed + ([self._current] if self._current else [])
        return " ".join(p for p in parts if p).strip()

    async def add_audio(self, audio_b64: str) -> None:
        # Always buffer for the batch fallback.
        self._audio_chunks.append(base64.b64decode(audio_b64))
        # Forward live to the streaming socket if it's healthy.
        if self._stream_alive and self._ws is not None:
            try:
                await self._ws.transcribe(audio_b64, encoding="audio/wav", sample_rate=self._sample_rate)
                self._sent_any = True
            except Exception as e:
                logger.warning("STT stream send failed (falling back to batch): %s", e)
                self._stream_alive = False

    def has_audio(self) -> bool:
        return len(self._audio_chunks) > 0 or self._sent_any

    def clear(self) -> None:
        self._audio_chunks.clear()
        self._sent_any = False
        self._committed = []
        self._current = ""

    async def transcribe(self) -> tuple[str, str, float]:
        # Streaming first: flush and wait briefly for the finalized transcript.
        if self._stream_alive and self._ws is not None and self._sent_any:
            try:
                start = time.time()
                await self._ws.flush()
                t = await self._await_final(deadline_s=1.5)
                if t:
                    lang = self._latest_language or "en-IN"
                    self.clear()
                    lat = (time.time() - start) * 1000
                    logger.info("STT(stream) transcript: '%s' [lang=%s] (%.0fms)", t, lang, lat)
                    return t, lang, lat
            except Exception as e:
                logger.warning("STT streaming transcribe failed (batch fallback): %s", e)
                self._stream_alive = False
        # Batch fallback (the original, proven path).
        return await self._batch_transcribe()

    async def _await_final(self, deadline_s: float) -> str:
        """Wait for the post-flush accumulated transcript to appear and stabilize."""
        deadline = time.time() + deadline_s
        last = self._full_transcript()
        stable_since: float | None = None
        while time.time() < deadline:
            await asyncio.sleep(0.05)
            cur = self._full_transcript()
            if cur and cur == last:
                if stable_since is None:
                    stable_since = time.time()
                elif time.time() - stable_since > 0.15:
                    break
            else:
                last = cur
                stable_since = None
        return self._full_transcript()

    async def _batch_transcribe(self) -> tuple[str, str, float]:
        if not self._audio_chunks:
            return "", "en-IN", 0.0

        pcm_data = b"".join(self._audio_chunks)
        self.clear()

        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._sample_rate)
            wf.writeframes(pcm_data)
        wav_buffer.seek(0)

        loop = asyncio.get_event_loop()
        start = time.time()

        def _call_stt():
            response = self._client.speech_to_text.transcribe(
                file=wav_buffer, model=self._model, mode=self._mode,
            )
            transcript = (response.transcript or "").strip()
            language_code = getattr(response, "language_code", None) or "en-IN"
            return transcript, language_code

        transcript, language_code = await loop.run_in_executor(_executor, _call_stt)
        latency_ms = (time.time() - start) * 1000
        logger.info("STT(batch) transcript: '%s' [lang=%s] (%.0fms)", transcript, language_code, latency_ms)
        return transcript, language_code, latency_ms

    async def close(self) -> None:
        if self._receiver is not None:
            self._receiver.cancel()
            self._receiver = None
        if self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception:
                pass
            self._cm = None
            self._ws = None
