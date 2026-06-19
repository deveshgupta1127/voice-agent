import asyncio
import base64
import logging
import re
import uuid
from typing import Any, Awaitable, Callable

from config import Settings
from agents.router_agent import RouterAgent
from agents.card_agent import CardAgent
from agents.account_agent import AccountAgent
from llm.provider_factory import get_provider
from tools.tool_registry import build_registry
from utils.metrics import LatencyTracker
from utils.logger import ConversationLogger
from .stt import SarvamSTT
from .tts import SarvamTTS

logger = logging.getLogger("voice_agent.orchestrator")


class PipelineOrchestrator:
    def __init__(
        self,
        llm_provider_name: str,
        event_callback: Callable[[dict], Awaitable[None]],
        settings: Settings,
        db,
    ):
        self._event_cb = event_callback
        self._settings = settings
        self._db = db

        self._llm = get_provider(llm_provider_name, settings)
        self._tool_registry = build_registry(db)

        self._agents = {
            "router": RouterAgent(self._llm, self._tool_registry),
            "card_agent": CardAgent(self._llm, self._tool_registry),
            "account_agent": AccountAgent(self._llm, self._tool_registry),
        }
        self._active_agent = self._agents["router"]

        self._session_id = str(uuid.uuid4())[:8]
        self._conversation_history: list[dict] = []
        self._session_state: dict = {
            "customer_id": None,
            "customer_name": None,
            "verified": False,
            "language": "en-IN",
        }

        self._latency = LatencyTracker()
        self._logger = ConversationLogger(self._session_id)
        self._turn_number = 0

        self._stt = SarvamSTT(
            api_key=settings.SARVAM_API_KEY,
            model=settings.STT_MODEL,
            mode=settings.STT_MODE,
            sample_rate=settings.STT_SAMPLE_RATE,
        )
        self._tts = SarvamTTS(
            api_key=settings.SARVAM_API_KEY,
            model=settings.TTS_MODEL,
            target_language=settings.TTS_TARGET_LANGUAGE,
            speaker=settings.TTS_SPEAKER,
        )

    async def start(self) -> None:
        await self._emit({"type": "state", "state": "ready"})
        logger.info("Session %s started", self._session_id)

    async def handle_audio_chunk(self, audio_b64: str) -> None:
        self._stt.add_audio_chunk(audio_b64)

    async def handle_stop_recording(self) -> None:
        if not self._stt.has_audio():
            logger.info("No audio to transcribe")
            return

        await self._emit({"type": "state", "state": "processing"})

        self._latency.reset()
        self._latency.mark("stt_start")

        transcript, stt_latency_ms = await self._stt.transcribe()

        self._latency.mark("stt_end")

        if not transcript:
            logger.info("Empty transcript, ignoring")
            await self._emit({"type": "state", "state": "ready"})
            return

        await self._emit({"type": "transcript_user", "text": transcript})
        await self._run_agent_turn(transcript)

    async def _run_agent_turn(self, user_text: str) -> None:
        self._turn_number += 1
        self._conversation_history.append({"role": "user", "content": user_text})

        self._latency.mark("llm_start")

        got_first = False

        async def on_text_delta(delta: str):
            nonlocal got_first
            if not got_first:
                self._latency.mark("llm_first_token")
                got_first = True
            await self._emit({"type": "transcript_agent", "text": delta, "delta": True})

        async def on_tool_call_start(name: str, args: dict):
            await self._emit({"type": "tool_call_start", "name": name, "args": args})

        async def on_tool_call_end(name: str, args: dict, result: Any, duration_ms: float):
            self._latency.add_tool_call_duration(duration_ms)
            await self._emit({
                "type": "tool_call_end",
                "name": name,
                "result": result,
                "duration_ms": round(duration_ms, 1),
            })

        response = await self._active_agent.run(
            self._conversation_history,
            self._session_state,
            on_text_delta,
            on_tool_call_start,
            on_tool_call_end,
        )

        self._latency.mark("llm_end")

        response_text = re.sub(r"\[HANDOVER:\s*\w+\]", "", response.text).strip()
        self._conversation_history.append({"role": "assistant", "content": response_text})

        self._update_session_state(response)

        if response.handover:
            target = response.handover["target_agent"]
            if target in self._agents:
                await self._emit({
                    "type": "agent_handover",
                    "from": self._active_agent.name,
                    "to": target,
                })
                self._active_agent = self._agents[target]

        await self._synthesize_speech(response_text)

        self._logger.log_turn(
            self._turn_number,
            user_text,
            self._active_agent.name,
            response_text,
            response.tool_calls_made,
            self._latency.get_metrics(),
            response.handover,
        )

    def _update_session_state(self, response) -> None:
        for tc in response.tool_calls_made:
            if tc["name"] == "verify_identity" and isinstance(tc["result"], dict):
                if tc["result"].get("verified"):
                    self._session_state["verified"] = True
                    self._session_state["customer_id"] = tc["result"].get("customer_id")
                    self._session_state["customer_name"] = tc["result"].get("customer_name")

    async def _synthesize_speech(self, text: str) -> None:
        await self._emit({"type": "state", "state": "speaking"})
        self._latency.mark("tts_start")

        try:
            wav_chunks = await self._tts.synthesize(text)

            self._latency.mark("tts_first_chunk")
            for chunk in wav_chunks:
                audio_b64 = base64.b64encode(chunk).decode("ascii")
                await self._emit({
                    "type": "audio_chunk",
                    "data": audio_b64,
                    "content_type": "audio/wav",
                })
        except Exception as e:
            logger.error("TTS error: %s", e)

        self._latency.mark("tts_end")

        metrics = self._latency.get_metrics()
        await self._emit({"type": "latency", "metrics": metrics})
        await self._emit({"type": "turn_complete"})
        await self._emit({"type": "state", "state": "ready"})

    async def shutdown(self) -> None:
        if self._turn_number > 0:
            self._logger.save()
        logger.info("Session %s shut down. Turns: %d", self._session_id, self._turn_number)

    async def _emit(self, event: dict) -> None:
        await self._event_cb(event)
