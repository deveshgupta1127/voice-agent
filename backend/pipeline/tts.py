import asyncio
import base64
import logging
from concurrent.futures import ThreadPoolExecutor

from sarvamai import SarvamAI

logger = logging.getLogger("voice_agent.tts")

_executor = ThreadPoolExecutor(max_workers=2)


class SarvamTTS:
    def __init__(
        self,
        api_key: str,
        model: str = "bulbul:v3",
        target_language: str = "en-IN",
        speaker: str = "shubh",
    ):
        self._client = SarvamAI(api_subscription_key=api_key)
        self._model = model
        self._target_language = target_language
        self._speaker = speaker

    async def synthesize(self, text: str) -> list[bytes]:
        loop = asyncio.get_event_loop()

        def _call_tts():
            response = self._client.text_to_speech.convert(
                text=text,
                target_language_code=self._target_language,
                model=self._model,
                speaker=self._speaker,
            )
            wav_chunks = []
            for audio_b64 in response.audios:
                wav_chunks.append(base64.b64decode(audio_b64))
            return wav_chunks

        chunks = await loop.run_in_executor(_executor, _call_tts)
        logger.info("TTS synthesized %d chunk(s) for: '%.40s...'", len(chunks), text)
        return chunks
