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

SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")


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

        self._current_turn_task: asyncio.Task | None = None
        self._spoken_sentences: list[str] = []

    async def start(self) -> None:
        await self._emit({"type": "state", "state": "ready"})
        logger.info("Session %s started", self._session_id)

    async def handle_audio_chunk(self, audio_b64: str) -> None:
        self._stt.add_audio_chunk(audio_b64)

    async def handle_stop_recording(self) -> None:
        if not self._stt.has_audio():
            logger.info("No audio to transcribe")
            return

        await self._cancel_current_turn()
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

        self._current_turn_task = asyncio.create_task(
            self._safe_run_turn(transcript)
        )

    async def handle_barge_in(self) -> None:
        logger.info("Barge-in detected, cancelling current turn")
        await self._cancel_current_turn()

        spoken = " ".join(self._spoken_sentences)
        if self._conversation_history and self._conversation_history[-1]["role"] == "user":
            if spoken:
                self._conversation_history.append({
                    "role": "assistant",
                    "content": spoken + " [interrupted by customer]",
                })
            else:
                self._conversation_history.append({
                    "role": "assistant",
                    "content": "[interrupted before responding]",
                })
        self._spoken_sentences = []

    async def _cancel_current_turn(self) -> None:
        if self._current_turn_task and not self._current_turn_task.done():
            self._current_turn_task.cancel()
            try:
                await self._current_turn_task
            except (asyncio.CancelledError, Exception):
                pass
            self._current_turn_task = None

    async def _safe_run_turn(self, transcript: str) -> None:
        try:
            await self._run_agent_turn(transcript)
        except asyncio.CancelledError:
            logger.info("Turn cancelled (barge-in)")
        except Exception as e:
            logger.error("Turn error: %s", e)
            await self._emit({"type": "error", "stage": "turn", "message": str(e)})
            await self._emit({"type": "state", "state": "ready"})

    async def _run_agent_turn(self, user_text: str) -> None:
        self._turn_number += 1
        self._spoken_sentences = []
        self._conversation_history.append({"role": "user", "content": user_text})

        await self._emit({"type": "state", "state": "processing"})
        self._latency.mark("llm_start")

        tts_queue: asyncio.Queue[str | None] = asyncio.Queue()
        text_buffer = ""
        got_first = False

        async def on_text_delta(delta: str):
            nonlocal text_buffer, got_first
            if not got_first:
                self._latency.mark("llm_first_token")
                got_first = True
            await self._emit({"type": "transcript_agent", "text": delta, "delta": True})

            text_buffer += delta
            while True:
                m = SENTENCE_END_RE.search(text_buffer)
                if not m:
                    break
                sentence = text_buffer[: m.start() + 1].strip()
                text_buffer = text_buffer[m.end() :]
                if sentence:
                    await tts_queue.put(sentence)

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

        tts_task = asyncio.create_task(self._tts_consumer(tts_queue))

        try:
            response = await self._active_agent.run(
                self._conversation_history,
                self._session_state,
                on_text_delta,
                on_tool_call_start,
                on_tool_call_end,
            )

            self._latency.mark("llm_end")

            remaining = text_buffer.strip()
            if remaining:
                await tts_queue.put(remaining)

            await tts_queue.put(None)
            await tts_task

            end_session = "[END_SESSION]" in response.text

            response_text = re.sub(r"\[HANDOVER:\s*\w+\]", "", response.text)
            response_text = response_text.replace("[END_SESSION]", "")
            response_text = response_text.strip()

            self._conversation_history.append({"role": "assistant", "content": response_text})

            self._update_session_state(response)

            handover_target = None
            if response.handover:
                target = response.handover["target_agent"]
                if target in self._agents:
                    await self._emit({
                        "type": "agent_handover",
                        "from": self._active_agent.name,
                        "to": target,
                    })
                    self._active_agent = self._agents[target]
                    if target != "router":
                        handover_target = target

            metrics = self._latency.get_metrics()
            await self._emit({"type": "latency", "metrics": metrics})
            await self._emit({"type": "turn_complete"})

            self._logger.log_turn(
                self._turn_number,
                user_text,
                self._active_agent.name,
                response_text,
                response.tool_calls_made,
                metrics,
                response.handover,
            )

            if end_session:
                await self._emit({"type": "session_ended"})
            elif handover_target:
                await self._run_agent_turn("[Customer transferred — proceed based on conversation history]")
            else:
                await self._emit({"type": "state", "state": "ready"})

        except asyncio.CancelledError:
            tts_task.cancel()
            try:
                await tts_task
            except (asyncio.CancelledError, Exception):
                pass
            raise

    async def _tts_consumer(self, queue: asyncio.Queue[str | None]) -> None:
        self._latency.mark("tts_start")
        first_chunk = True

        while True:
            sentence = await queue.get()
            if sentence is None:
                break

            clean = sentence.replace("[END_SESSION]", "").strip()
            clean = re.sub(r"\[HANDOVER:\s*\w+\]", "", clean).strip()
            if not clean:
                continue

            try:
                wav_chunks = await self._tts.synthesize(clean)
                if first_chunk:
                    self._latency.mark("tts_first_chunk")
                    await self._emit({"type": "state", "state": "speaking"})
                    first_chunk = False
                for chunk in wav_chunks:
                    audio_b64 = base64.b64encode(chunk).decode("ascii")
                    await self._emit({
                        "type": "audio_chunk",
                        "data": audio_b64,
                        "content_type": "audio/wav",
                    })
                self._spoken_sentences.append(clean)
            except Exception as e:
                logger.error("TTS error for sentence: %s", e)

        self._latency.mark("tts_end")

    def _update_session_state(self, response) -> None:
        for tc in response.tool_calls_made:
            if tc["name"] == "verify_identity" and isinstance(tc["result"], dict):
                if tc["result"].get("verified"):
                    self._session_state["verified"] = True
                    self._session_state["customer_id"] = tc["result"].get("customer_id")
                    self._session_state["customer_name"] = tc["result"].get("customer_name")

    async def shutdown(self) -> None:
        await self._cancel_current_turn()
        if self._turn_number > 0:
            self._logger.save()
        logger.info("Session %s shut down. Turns: %d", self._session_id, self._turn_number)

    async def _emit(self, event: dict) -> None:
        await self._event_cb(event)
