import json
import logging
from typing import Any, AsyncGenerator

from groq import AsyncGroq
from .base_provider import BaseLLMProvider, StreamEvent

logger = logging.getLogger("voice_agent.groq")


class GroqProvider(BaseLLMProvider):
    """OpenAI-compatible streaming + tool-use provider for GroqCloud.

    Mirrors SarvamProvider (both speak the OpenAI chat-completions dialect); the
    only differences are the SDK entrypoint (client.chat.completions.create) and
    that the default model qwen/qwen3.6-27b is a reasoning model — we disable its
    thinking via reasoning_effort="none" so the spoken TTS text and the
    [HANDOVER:]/[END_SESSION] markers the orchestrator parses stay clean and
    latency stays low.
    """

    def __init__(self, api_key: str, model: str = "qwen/qwen3.6-27b"):
        self._client = AsyncGroq(api_key=api_key)
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

        if system_prompt:
            api_messages.insert(0, {"role": "system", "content": system_prompt})

        kwargs = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            # Disable Qwen3 "thinking" so no <think> reasoning leaks into the
            # spoken response or the handover markers. Sent via extra_body so it
            # works regardless of the installed groq SDK version.
            "extra_body": {"reasoning_effort": "none"},
        }
        if tools:
            kwargs["tools"] = self.format_tool_definitions(tools)

        tool_calls_acc: dict[int, dict] = {}

        response = await self._client.chat.completions.create(**kwargs)

        async for chunk in response:
            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            delta = choice.delta

            if delta and delta.content:
                yield StreamEvent(type="text_delta", text=delta.content)

            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"id": tc.id or "", "name": "", "arguments": ""}
                    if tc.id:
                        tool_calls_acc[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_acc[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc.function.arguments

            # Flush on ANY terminal finish_reason — not only "tool_calls" — so a
            # tool call is never dropped if the model ends the turn with
            # finish_reason="stop"/"length" while tool calls are pending.
            if choice.finish_reason:
                for idx in sorted(tool_calls_acc.keys()):
                    tc = tool_calls_acc[idx]
                    try:
                        args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    except json.JSONDecodeError:
                        logger.warning(
                            "Groq: malformed tool-call JSON for %s, defaulting to {}: %r",
                            tc["name"], tc["arguments"],
                        )
                        args = {}
                    yield StreamEvent(
                        type="tool_use",
                        tool_name=tc["name"],
                        tool_args=args,
                        tool_use_id=tc["id"],
                    )
                tool_calls_acc = {}
                yield StreamEvent(type="message_end")

    def format_tool_result(self, tool_use_id: str, result: Any) -> dict:
        return {
            "role": "tool",
            "tool_call_id": tool_use_id,
            "content": json.dumps(result) if not isinstance(result, str) else result,
        }

    def format_tool_definitions(self, tools: list[dict]) -> list[dict]:
        formatted = []
        for tool in tools:
            formatted.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                },
            })
        return formatted

    def format_assistant_tool_calls(self, text: str, tool_calls: list) -> dict:
        msg: dict = {"role": "assistant", "content": text or ""}
        tc_list = []
        for tc in tool_calls:
            tc_list.append({
                "id": tc.tool_use_id,
                "type": "function",
                "function": {
                    "name": tc.tool_name,
                    "arguments": json.dumps(tc.tool_args) if tc.tool_args else "{}",
                },
            })
        msg["tool_calls"] = tc_list
        return msg

    def format_tool_results_message(self, results: list[dict]) -> list[dict]:
        messages = []
        for r in results:
            messages.append({
                "role": "tool",
                "tool_call_id": r["tool_use_id"],
                "content": r["content"],
            })
        return messages
