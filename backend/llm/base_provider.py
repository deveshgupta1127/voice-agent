from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncGenerator


@dataclass
class StreamEvent:
    type: str  # "text_delta" | "tool_use" | "message_end"
    text: str | None = None
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_use_id: str | None = None


class BaseLLMProvider(ABC):
    @abstractmethod
    async def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[StreamEvent, None]:
        ...

    @abstractmethod
    def format_tool_result(self, tool_use_id: str, result: Any) -> dict:
        ...

    @abstractmethod
    def format_tool_definitions(self, tools: list[dict]) -> list[dict]:
        ...
