import csv
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

LOGS_DIR = Path(__file__).parent.parent / "logs"
SESSION_LOGS_DIR = LOGS_DIR / "sessions"
LATENCY_LOG = LOGS_DIR / "latency.csv"

logger = logging.getLogger("voice_agent")

_LATENCY_FIELDS = ["timestamp", "session_id", "provider", "turn",
                   "response_ms", "total_ms", "stt_ms", "llm_ms",
                   "tts_ttfb_ms", "tts_ms", "wait_ms", "emit_ms", "recovery_ms", "tool_ms"]


def log_latency(session_id: str, provider: str, metrics: dict) -> None:
    """Append one turn's latency to logs/latency.csv for offline analysis.

    response_ms = user stopped speaking -> agent's first audio (what users feel).
    total_ms    = user stopped speaking -> agent finished speaking.
    tts_ttfb_ms = first sentence sent to TTS -> first audio chunk (pure TTS speed).
    tts_ms      = ACTIVE Sarvam synthesis only (browser-send + LLM-gap excluded).
    wait_ms     = TTS sat idle waiting for the (slow) LLM to stream more text.
    emit_ms     = time spent pushing audio to the browser (backpressure).
    recovery_ms = socket warm/reconnect paid on the hot path (~0 when pre-warmed).
    """
    try:
        LOGS_DIR.mkdir(exist_ok=True)
        new_file = not LATENCY_LOG.exists()
        if not new_file:
            # Schema changed? Rotate the old file so columns don't silently misalign.
            try:
                with open(LATENCY_LOG, "r", encoding="utf-8") as f:
                    header = f.readline().strip().split(",")
                if header != _LATENCY_FIELDS:
                    LATENCY_LOG.replace(LATENCY_LOG.with_name("latency.old.csv"))
                    new_file = True
            except Exception:
                pass
        with open(LATENCY_LOG, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(_LATENCY_FIELDS)
            w.writerow([
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                session_id, provider, metrics.get("turn"),
                metrics.get("response_ms"), metrics.get("total_ms"),
                metrics.get("stt_ms"), metrics.get("llm_ms"),
                metrics.get("tts_ttfb_ms"), metrics.get("tts_ms"),
                metrics.get("wait_ms"), metrics.get("emit_ms"),
                metrics.get("recovery_ms"), metrics.get("tool_ms"),
            ])
    except Exception as e:
        logger.warning("latency log write failed: %s", e)


def setup_logging():
    LOGS_DIR.mkdir(exist_ok=True)
    SESSION_LOGS_DIR.mkdir(exist_ok=True)

    root_logger = logging.getLogger("voice_agent")
    root_logger.setLevel(logging.DEBUG)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))

    server_log_path = LOGS_DIR / "server.log"
    file_handler = logging.FileHandler(server_log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))

    root_logger.addHandler(console)
    root_logger.addHandler(file_handler)

    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)


class ConversationLogger:
    def __init__(self, session_id: str):
        self._session_id = session_id
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._turns: list[dict] = []
        self._errors: list[dict] = []

    def log_turn(
        self,
        turn_number: int,
        user_text: str,
        agent_name: str,
        agent_response: str,
        tool_calls: list[dict],
        metrics: dict,
        handover: dict | None = None,
    ) -> None:
        serializable_tool_calls = []
        for tc in tool_calls:
            serializable_tool_calls.append({
                "name": tc.get("name"),
                "args": tc.get("args"),
                "result": _make_serializable(tc.get("result")),
                "duration_ms": tc.get("duration_ms"),
            })

        entry = {
            "turn": turn_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user": user_text,
            "agent": agent_name,
            "response": agent_response,
            "tool_calls": serializable_tool_calls,
            "metrics": metrics,
            "handover": handover,
        }
        self._turns.append(entry)

        logger.info(
            "[%s] Turn %d | Agent: %s | Tools: %d | Total: %sms | User: '%.50s' | Response: '%.80s'",
            self._session_id,
            turn_number,
            agent_name,
            len(tool_calls),
            metrics.get("total_ms", "N/A"),
            user_text,
            agent_response,
        )

    def log_error(self, stage: str, error: str) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "error": error,
        }
        self._errors.append(entry)
        logger.error("[%s] Stage: %s | Error: %s", self._session_id, stage, error)

    def save(self) -> str:
        session_data = {
            "session_id": self._session_id,
            "started_at": self._started_at,
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "total_turns": len(self._turns),
            "turns": self._turns,
            "errors": self._errors,
        }

        filename = f"{self._session_id}.json"
        filepath = SESSION_LOGS_DIR / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False, default=str)

        logger.info("[%s] Session log saved to %s (%d turns)", self._session_id, filepath, len(self._turns))
        return str(filepath)

    def get_full_log(self) -> list[dict]:
        return self._turns


def _make_serializable(obj):
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_serializable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)
