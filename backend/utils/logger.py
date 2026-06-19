import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("voice_agent")


class ConversationLogger:
    def __init__(self, session_id: str):
        self._session_id = session_id
        self._turns: list[dict] = []

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
        entry = {
            "session_id": self._session_id,
            "turn": turn_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user": user_text,
            "agent": agent_name,
            "response": agent_response,
            "tool_calls": tool_calls,
            "metrics": metrics,
            "handover": handover,
        }
        self._turns.append(entry)

        logger.info(
            "Turn %d | Agent: %s | Tools: %d | Total: %sms",
            turn_number,
            agent_name,
            len(tool_calls),
            metrics.get("total_ms", "N/A"),
        )

    def log_error(self, stage: str, error: str) -> None:
        logger.error("Session %s | Stage: %s | Error: %s", self._session_id, stage, error)

    def get_full_log(self) -> list[dict]:
        return self._turns
