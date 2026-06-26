import asyncio
import base64
import logging
import re
import time
import uuid
from typing import Any, Awaitable, Callable

from config import Settings
from agents.router_agent import RouterAgent
from agents.card_agent import CardAgent
from agents.account_agent import AccountAgent
from agents.transaction_agent import TransactionAgent
from agents.payment_agent import PaymentAgent
from llm.provider_factory import get_provider
from tools.tool_registry import build_registry
from rag.pipeline import RAGPipeline
from utils.logger import ConversationLogger, log_latency
from .stt import SarvamSTT
from .tts import SarvamTTS

logger = logging.getLogger("voice_agent.orchestrator")

CHUNK_SPLIT_RE = re.compile(r"(?<=[.!?,;:])\s+")

# Guard against a runaway router<->specialist handover loop within one user turn.
MAX_HANDOVER_STEPS = 6


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
        self._provider_name = llm_provider_name

        self._llm = get_provider(llm_provider_name, settings)
        self._rag = RAGPipeline()
        self._tool_registry = build_registry(db, rag=self._rag)

        self._agents = {
            "router": RouterAgent(self._llm, self._tool_registry),
            "card_agent": CardAgent(self._llm, self._tool_registry),
            "account_agent": AccountAgent(self._llm, self._tool_registry),
            "transaction_agent": TransactionAgent(self._llm, self._tool_registry),
            "payment_agent": PaymentAgent(self._llm, self._tool_registry),
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

        self._logger = ConversationLogger(self._session_id)
        self._turn_number = 0

        self._stt = SarvamSTT(
            api_key=settings.SARVAM_API_KEY,
            model=settings.STT_MODEL,
            mode=settings.STT_MODE,
            sample_rate=settings.STT_SAMPLE_RATE,
            streaming=settings.STT_STREAMING,
        )
        self._tts = SarvamTTS(
            api_key=settings.SARVAM_API_KEY,
            model=settings.TTS_MODEL,
            target_language=settings.TTS_TARGET_LANGUAGE,
            speaker=settings.TTS_SPEAKER,
        )

        self._current_turn_task: asyncio.Task | None = None
        self._spoken_sentences: list[str] = []

        # Per-user-turn latency accumulators (a "turn" = one user utterance ->
        # the agent's spoken response, spanning any silent agent handover).
        self._turn_t0: float | None = None          # user finished speaking
        self._turn_stt_ms: float = 0.0
        self._turn_first_audio_t: float | None = None  # agent started speaking
        self._turn_last_audio_t: float | None = None   # agent finished speaking
        self._turn_llm_ms: float = 0.0
        self._turn_tts_ms: float = 0.0          # active Sarvam synthesis (excl. browser send + LLM gaps)
        self._turn_tts_ttfb_ms: float | None = None  # 1st sentence sent -> 1st audio (pure TTS latency)
        self._turn_wait_ms: float = 0.0         # TTS idle, waiting for the LLM to stream the next sentence
        self._turn_emit_ms: float = 0.0         # time spent sending audio to the browser (backpressure)
        self._turn_recovery_ms: float = 0.0     # socket warm/reconnect paid on the hot path (~0 if pre-warmed)
        self._turn_tool_ms: float = 0.0

    async def start(self) -> None:
        try:
            await self._tts.connect()  # persistent streaming socket (handshake ~1s, amortized)
        except Exception as e:
            logger.warning("TTS pre-connect failed (will retry lazily): %s", e)
        try:
            await self._stt.connect_stream()  # streaming STT (falls back to batch on any failure)
        except Exception as e:
            logger.warning("STT pre-connect failed (will use batch): %s", e)
        await self._emit({"type": "state", "state": "ready"})
        logger.info("Session %s started", self._session_id)

    async def handle_audio_chunk(self, audio_b64: str) -> None:
        await self._stt.add_audio(audio_b64)

    async def handle_stop_recording(self) -> None:
        if not self._stt.has_audio():
            logger.info("No audio to transcribe")
            return

        await self._cancel_current_turn()
        # Warm/clean the TTS socket NOW, in the background, so any handshake or
        # post-barge-in drain overlaps STT + LLM instead of delaying first audio.
        self._tts.prewarm()
        await self._emit({"type": "state", "state": "processing"})

        # The turn clock starts the moment the customer stops speaking.
        self._turn_t0 = time.time()
        stt_t0 = time.time()
        transcript, detected_language, _ = await self._stt.transcribe()
        self._turn_stt_ms = (time.time() - stt_t0) * 1000
        self._session_state["language"] = detected_language

        if not transcript:
            logger.info("Empty transcript, ignoring")
            await self._emit({"type": "state", "state": "ready"})
            return

        await self._emit({"type": "transcript_user", "text": transcript})

        self._current_turn_task = asyncio.create_task(
            self._safe_run_user_turn(transcript)
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

    async def _safe_run_user_turn(self, transcript: str) -> None:
        try:
            await self._run_user_turn(transcript)
        except asyncio.CancelledError:
            logger.info("Turn cancelled (barge-in)")
        except Exception as e:
            logger.error("Turn error: %s", e)
            await self._emit({"type": "error", "stage": "turn", "message": str(e)})
            await self._emit({"type": "state", "state": "ready"})

    async def _run_user_turn(self, user_text: str) -> None:
        """One user utterance -> one spoken response.

        Runs the active agent; if it hands over to a specialist, the next agent
        runs in the same turn (silently, the customer never hears a transfer).
        A single turn_latency + turn_complete is emitted at the end.
        """
        self._turn_number += 1
        turn_no = self._turn_number

        # Reset per-turn accumulators (stt_ms was already measured in stop_recording).
        self._spoken_sentences = []
        self._turn_first_audio_t = None
        self._turn_last_audio_t = None
        self._turn_llm_ms = 0.0
        self._turn_tts_ms = 0.0
        self._turn_tts_ttfb_ms = None
        self._turn_wait_ms = 0.0
        self._turn_emit_ms = 0.0
        self._turn_recovery_ms = 0.0
        self._turn_tool_ms = 0.0

        text = user_text
        append_user = True
        end_session = False
        steps = 0
        visited: set[str] = set()   # specialists already entered this turn
        route_exhausted = False     # force the router to answer directly (no more routing)

        while True:
            response, handover_target, step_end = await self._run_agent_step(
                text, append_user, turn_no, route_exhausted
            )
            end_session = end_session or step_end
            steps += 1

            if end_session or handover_target is None or steps >= MAX_HANDOVER_STEPS:
                break
            if route_exhausted:
                # The router already had its one forced chance to answer directly;
                # don't honour another handover — stop the turn here.
                break
            if handover_target != "router" and handover_target in visited:
                # About to RE-ENTER a specialist that already ran this turn — a
                # router<->specialist ping-pong (the loan-query loop). Send it back
                # to the router ONCE and force a direct answer instead of looping.
                # Each hop is a full LLM call, so this is also the big latency saver.
                logger.info("Routing loop detected (re-entry of %s); forcing router to answer", handover_target)
                self._active_agent = self._agents["router"]
                route_exhausted = True
            elif handover_target != "router":
                visited.add(handover_target)
            # Continue silently with the selected agent. No synthetic message: the
            # customer's request is already the last user turn in history.
            text = None
            append_user = False

        await self._emit_turn_latency(turn_no)
        await self._emit({"type": "turn_complete"})

        if end_session:
            await self._emit({"type": "session_ended"})
        else:
            await self._emit({"type": "state", "state": "ready"})

    async def _run_agent_step(self, user_text, append_user: bool, turn_no: int,
                              route_exhausted: bool = False):
        """Run the currently-active agent once: stream text, run tools, speak.

        Returns (response, handover_target, end_session). handover_target is the
        specialist to continue with in this same turn, or None (done / handed
        back to router). When route_exhausted is set, the router is told to stop
        routing and answer the customer directly (loop-breaker).
        """
        if append_user and user_text is not None:
            self._conversation_history.append({"role": "user", "content": user_text})
        if route_exhausted:
            self._session_state["_route_exhausted"] = True
        await self._emit({"type": "state", "state": "processing"})

        tts_queue: asyncio.Queue[str | None] = asyncio.Queue()
        text_buffer = ""

        async def on_text_delta(delta: str):
            nonlocal text_buffer
            await self._emit({"type": "transcript_agent", "text": delta, "delta": True})

            text_buffer += delta
            while True:
                m = CHUNK_SPLIT_RE.search(text_buffer)
                if not m:
                    break
                sentence = text_buffer[: m.start() + 1].strip()
                text_buffer = text_buffer[m.end() :]
                if sentence:
                    await tts_queue.put(sentence)

        async def on_tool_call_start(name: str, args: dict):
            await self._emit({"type": "tool_call_start", "name": name, "args": args})

        async def on_tool_call_end(name: str, args: dict, result: Any, duration_ms: float):
            self._turn_tool_ms += duration_ms
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

            self._turn_llm_ms += response.llm_total_ms or 0

            remaining = text_buffer.strip()
            if remaining:
                await tts_queue.put(remaining)

            await tts_queue.put(None)
            await tts_task

            end_session = "[END_SESSION]" in response.text

            response_text = re.sub(r"\[HANDOVER:\s*\w+\]", "", response.text)
            response_text = response_text.replace("[END_SESSION]", "")
            response_text = response_text.strip()

            # Don't store an empty assistant turn (silent routing produces one)
            # — empty content can be rejected by providers on the next call.
            if response_text:
                self._conversation_history.append({"role": "assistant", "content": response_text})

            was_verified = self._session_state.get("verified", False)
            self._update_session_state(response)
            if not was_verified and self._session_state.get("verified"):
                await self._prefetch_customer_data()

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
                    elif not response_text:
                        # Specialist handed back to router without saying anything
                        # (e.g. an out-of-scope request) — let the router recover
                        # this turn instead of leaving the customer in silence.
                        handover_target = "router"
                else:
                    logger.warning("Unknown handover target ignored: %s", target)

            self._logger.log_turn(
                turn_no,
                user_text or "",
                self._active_agent.name,
                response_text,
                response.tool_calls_made,
                {},
                response.handover,
            )

            return response, handover_target, end_session

        except asyncio.CancelledError:
            tts_task.cancel()
            try:
                await tts_task
            except (asyncio.CancelledError, Exception):
                pass
            raise
        finally:
            self._session_state.pop("_route_exhausted", None)

    async def _tts_consumer(self, queue: asyncio.Queue[str | None]) -> None:
        started = False  # has the first sentence begun synthesizing?

        async def on_wav(wav_bytes: bytes) -> None:
            if self._turn_first_audio_t is None:
                # First audible chunk of the turn -> the agent has "responded".
                self._turn_first_audio_t = time.time()
                await self._emit({"type": "state", "state": "speaking"})
            audio_b64 = base64.b64encode(wav_bytes).decode("ascii")
            await self._emit({
                "type": "audio_chunk",
                "data": audio_b64,
                "content_type": "audio/wav",
            })
            self._turn_last_audio_t = time.time()

        while True:
            g0 = time.time()
            sentence = await queue.get()
            # Time blocked here AFTER synthesis has begun = TTS sitting idle while
            # the (slow) LLM streams the next sentence. Before the first sentence
            # it's just LLM time-to-first-token (already reflected in response_ms).
            if started and sentence is not None:
                self._turn_wait_ms += (time.time() - g0) * 1000
            if sentence is None:
                break

            clean = re.sub(r"\[.*?\]", "", sentence).strip()
            clean = re.sub(r"\[.*$", "", clean).strip()
            clean = re.sub(r"^[^\[]*\]", "", clean).strip()
            if not clean:
                continue

            try:
                tts_language = self._session_state.get("language", "en-IN")
                stats = await self._tts.synthesize_stream(clean, tts_language, on_wav)
                started = True
                self._spoken_sentences.append(clean)

                # Decompose this sentence's time honestly:
                #   tts_ms   = pure Sarvam synthesis (synth minus browser-send time)
                #   emit_ms  = time spent pushing audio to the browser (backpressure)
                #   recovery = socket warm/reconnect on the hot path (~0 if pre-warmed)
                synth = stats.get("synth_ms") or 0.0
                emit = stats.get("emit_ms") or 0.0
                self._turn_tts_ms += max(synth - emit, 0.0)
                self._turn_emit_ms += emit
                self._turn_recovery_ms += stats.get("recovery_ms") or 0.0
                if self._turn_tts_ttfb_ms is None and stats.get("ttfb_ms") is not None:
                    self._turn_tts_ttfb_ms = stats["ttfb_ms"]
            except Exception as e:
                logger.error("TTS error for sentence: %s", e)

    async def _emit_turn_latency(self, turn_no: int) -> None:
        t0 = self._turn_t0 or time.time()
        response_ms = (
            round((self._turn_first_audio_t - t0) * 1000, 1)
            if self._turn_first_audio_t is not None
            else None
        )
        total_ms = (
            round((self._turn_last_audio_t - t0) * 1000, 1)
            if self._turn_last_audio_t is not None
            else round((time.time() - t0) * 1000, 1)
        )
        metrics = {
            "turn": turn_no,
            "response_ms": response_ms,   # user stopped speaking -> agent's FIRST audio (what users feel)
            "total_ms": total_ms,         # user stopped speaking -> agent finished speaking
            "stt_ms": round(self._turn_stt_ms, 1),
            "llm_ms": round(self._turn_llm_ms, 1),
            "tts_ttfb_ms": round(self._turn_tts_ttfb_ms, 1) if self._turn_tts_ttfb_ms is not None else None,
            "tts_ms": round(self._turn_tts_ms, 1),     # active Sarvam synthesis only
            "wait_ms": round(self._turn_wait_ms, 1),   # TTS idle, waiting on the LLM to stream more
            "emit_ms": round(self._turn_emit_ms, 1),   # sending audio to the browser (backpressure)
            "recovery_ms": round(self._turn_recovery_ms, 1),  # socket warm on hot path (~0 if pre-warm works)
            "tool_ms": round(self._turn_tool_ms, 1),
        }
        log_latency(self._session_id, self._provider_name, metrics)
        await self._emit({"type": "turn_latency", "metrics": metrics})

    def _update_session_state(self, response) -> None:
        for tc in response.tool_calls_made:
            if tc["name"] == "verify_identity" and isinstance(tc["result"], dict):
                if tc["result"].get("verified"):
                    self._session_state["verified"] = True
                    self._session_state["customer_id"] = tc["result"].get("customer_id")
                    self._session_state["customer_name"] = tc["result"].get("customer_name")

    async def _prefetch_customer_data(self) -> None:
        """Load the customer's accounts + cards once verified so specialists can
        act without an extra get_customer_accounts / get_card_list round-trip."""
        cid = self._session_state.get("customer_id")
        if not cid:
            return
        try:
            from database.queries import get_accounts_by_customer, get_cards_by_customer
            self._session_state["accounts"] = await get_accounts_by_customer(self._db, cid)
            self._session_state["cards"] = await get_cards_by_customer(self._db, cid)
            logger.info("Prefetched %d account(s), %d card(s) for %s",
                        len(self._session_state["accounts"]), len(self._session_state["cards"]), cid)
        except Exception as e:
            logger.warning("Customer data prefetch failed: %s", e)

    async def shutdown(self) -> None:
        await self._cancel_current_turn()
        try:
            await self._tts.close()
        except Exception:
            pass
        try:
            await self._stt.close()
        except Exception:
            pass
        if self._turn_number > 0:
            self._logger.save()
        logger.info("Session %s shut down. Turns: %d", self._session_id, self._turn_number)

    async def _emit(self, event: dict) -> None:
        await self._event_cb(event)
