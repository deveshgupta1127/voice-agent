import asyncio
import base64
import io
import logging
import struct
import wave
from concurrent.futures import ThreadPoolExecutor

from sarvamai import SarvamAI

logger = logging.getLogger("voice_agent.stt")

_executor = ThreadPoolExecutor(max_workers=2)


class SarvamSTT:
    def __init__(
        self,
        api_key: str,
        model: str = "saaras:v3",
        language: str = "unknown",
        mode: str = "transcribe",
        sample_rate: int = 16000,
    ):
        self._client = SarvamAI(api_subscription_key=api_key)
        self._model = model
        self._language = language
        self._mode = mode
        self._sample_rate = sample_rate
        self._audio_chunks: list[bytes] = []

    def add_audio_chunk(self, audio_b64: str) -> None:
        raw_pcm = base64.b64decode(audio_b64)
        self._audio_chunks.append(raw_pcm)

    def clear(self) -> None:
        self._audio_chunks.clear()

    def has_audio(self) -> bool:
        return len(self._audio_chunks) > 0

    async def transcribe(self) -> tuple[str, float]:
        if not self._audio_chunks:
            return "", 0.0

        pcm_data = b"".join(self._audio_chunks)
        self._audio_chunks.clear()

        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._sample_rate)
            wf.writeframes(pcm_data)
        wav_buffer.seek(0)

        loop = asyncio.get_event_loop()
        import time
        start = time.time()

        def _call_stt():
            response = self._client.speech_to_text.transcribe(
                file=wav_buffer,
                model=self._model,
                mode=self._mode,
            )
            return (response.transcript or "").strip()

        transcript = await loop.run_in_executor(_executor, _call_stt)
        latency_ms = (time.time() - start) * 1000

        logger.info("STT transcript: '%s' (%.0fms)", transcript, latency_ms)
        return transcript, latency_ms
