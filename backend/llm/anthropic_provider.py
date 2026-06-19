import json
from typing import Any, AsyncGenerator
import anthropic
from .base_provider import BaseLLMProvider, StreamEvent


class AnthropicProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[StreamEvent, None]:
        system_prompt = None
        api_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            else:
                api_messages.append(msg)

        kwargs = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = self.format_tool_definitions(tools)

        current_tool_name = None
        current_tool_id = None
        current_tool_json = ""

        async with self._client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_start":
                    if hasattr(event.content_block, "type"):
                        if event.content_block.type == "tool_use":
                            current_tool_name = event.content_block.name
                            current_tool_id = event.content_block.id
                            current_tool_json = ""

                elif event.type == "content_block_delta":
                    if hasattr(event.delta, "type"):
                        if event.delta.type == "text_delta":
                            yield StreamEvent(type="text_delta", text=event.delta.text)
                        elif event.delta.type == "input_json_delta":
                            current_tool_json += event.delta.partial_json

                elif event.type == "content_block_stop":
                    if current_tool_name is not None:
                        try:
                            args = json.loads(current_tool_json) if current_tool_json else {}
                        except json.JSONDecodeError:
                            args = {}
                        yield StreamEvent(
                            type="tool_use",
                            tool_name=current_tool_name,
                            tool_args=args,
                            tool_use_id=current_tool_id,
                        )
                        current_tool_name = None
                        current_tool_id = None
                        current_tool_json = ""

                elif event.type == "message_stop":
                    yield StreamEvent(type="message_end")

    def format_tool_result(self, tool_use_id: str, result: Any) -> dict:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": json.dumps(result) if not isinstance(result, str) else result,
                }
            ],
        }

    def format_tool_definitions(self, tools: list[dict]) -> list[dict]:
        formatted = []
        for tool in tools:
            formatted.append({
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["parameters"],
            })
        return formatted
