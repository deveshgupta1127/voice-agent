import time


class LatencyTracker:
    def __init__(self):
        self._timestamps: dict[str, float] = {}

    def mark(self, event_name: str) -> None:
        self._timestamps[event_name] = time.time()

    def get_metrics(self) -> dict:
        def diff(start: str, end: str) -> float | None:
            if start in self._timestamps and end in self._timestamps:
                return round((self._timestamps[end] - self._timestamps[start]) * 1000, 1)
            return None

        return {
            "stt_ms": diff("stt_start", "stt_end"),
            "llm_first_token_ms": diff("llm_start", "llm_first_token"),
            "llm_total_ms": diff("llm_start", "llm_end"),
            "tts_first_chunk_ms": diff("tts_start", "tts_first_chunk"),
            "tts_total_ms": diff("tts_start", "tts_end"),
            "total_ms": diff("stt_start", "tts_end"),
            "tool_calls_ms": self._timestamps.get("tool_calls_total_ms", 0),
        }

    def add_tool_call_duration(self, duration_ms: float) -> None:
        self._timestamps["tool_calls_total_ms"] = self._timestamps.get("tool_calls_total_ms", 0) + duration_ms

    def reset(self) -> None:
        self._timestamps.clear()
