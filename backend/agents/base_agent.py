import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from llm.base_provider import BaseLLMProvider
from tools.tool_registry import ToolRegistry


@dataclass
class AgentResponse:
    text: str
    tool_calls_made: list[dict] = field(default_factory=list)
    handover: dict | None = None
    llm_first_token_ms: float = 0
    llm_total_ms: float = 0


class BaseAgent(ABC):
    def __init__(
        self,
        llm_provider: BaseLLMProvider,
        tool_registry: ToolRegistry,
        agent_name: str,
    ):
        self._llm = llm_provider
        self._tools = tool_registry
        self._name = agent_name

    @property
    def name(self) -> str:
        return self._name

    @abstractmethod
    def get_system_prompt(self, session_state: dict) -> str:
        ...

    @abstractmethod
    def get_tool_names(self) -> list[str]:
        ...

    async def run(
        self,
        conversation_history: list[dict],
        session_state: dict,
        on_text_delta: Callable[[str], Awaitable[None]],
        on_tool_call_start: Callable[[str, dict], Awaitable[None]],
        on_tool_call_end: Callable[[str, dict, Any, float], Awaitable[None]],
    ) -> AgentResponse:
        tool_names = self.get_tool_names()
        tool_defs = self._tools.get_definitions(tool_names) if tool_names else None
        system_prompt = self.get_system_prompt(session_state)

        messages = [{"role": "system", "content": system_prompt}] + self._normalize_history(conversation_history)

        full_text = ""
        tool_calls_made = []
        first_token_ms = 0.0
        llm_start = time.time()
        got_first_token = False

        while True:
            current_text = ""
            pending_tool_calls = []

            async for event in self._llm.stream(messages, tool_defs):
                if event.type == "text_delta" and event.text:
                    if not got_first_token:
                        first_token_ms = (time.time() - llm_start) * 1000
                        got_first_token = True
                    current_text += event.text
                    await on_text_delta(event.text)

                elif event.type == "tool_use":
                    pending_tool_calls.append(event)

            if not pending_tool_calls:
                full_text += current_text
                break

            full_text += current_text
            messages.append(
                self._llm.format_assistant_tool_calls(current_text, pending_tool_calls)
            )

            tool_results = []
            for tc in pending_tool_calls:
                await on_tool_call_start(tc.tool_name, tc.tool_args)
                tool_start = time.time()
                try:
                    result = await self._tools.execute(tc.tool_name, tc.tool_args)
                except Exception as e:
                    result = {"error": str(e)}
                duration_ms = (time.time() - tool_start) * 1000

                tool_calls_made.append({
                    "name": tc.tool_name,
                    "args": tc.tool_args,
                    "result": result,
                    "duration_ms": duration_ms,
                })
                await on_tool_call_end(tc.tool_name, tc.tool_args, result, duration_ms)

                tool_results.append({
                    "tool_use_id": tc.tool_use_id,
                    "content": str(result) if not isinstance(result, str) else result,
                })

            messages.extend(self._llm.format_tool_results_message(tool_results))

        llm_total_ms = (time.time() - llm_start) * 1000

        handover = self._parse_handover(full_text)

        return AgentResponse(
            text=full_text,
            tool_calls_made=tool_calls_made,
            handover=handover,
            llm_first_token_ms=first_token_ms,
            llm_total_ms=llm_total_ms,
        )

    def _parse_handover(self, text: str) -> dict | None:
        match = re.search(r"\[HANDOVER:\s*(\w+)\]", text)
        if match:
            return {"target_agent": match.group(1)}
        return None

    @staticmethod
    def _normalize_history(history: list[dict]) -> list[dict]:
        """Clean the history into a non-empty, alternating-role sequence.

        Silent routing can leave an empty assistant turn or two user turns in a
        row in the conversation history; providers like Anthropic reject empty
        content and require alternating roles. Drop empty-text messages and
        merge consecutive same-role messages so any history is always valid.
        """
        out: list[dict] = []
        for msg in history:
            content = msg.get("content")
            if isinstance(content, str) and not content.strip():
                continue
            if (
                out
                and out[-1]["role"] == msg["role"]
                and isinstance(out[-1].get("content"), str)
                and isinstance(content, str)
            ):
                out[-1] = {"role": msg["role"], "content": out[-1]["content"] + "\n" + content}
            else:
                out.append({"role": msg["role"], "content": content})
        # Bound prefill cost on long calls — keep only recent context, and don't
        # start the window mid-exchange on an assistant turn.
        if len(out) > 16:
            out = out[-16:]
            while out and out[0].get("role") != "user":
                out.pop(0)
        return out

    @staticmethod
    def _accounts_summary(session_state: dict) -> str:
        accts = session_state.get("accounts") or []
        if not accts:
            return "(not pre-loaded — call get_customer_accounts first)"
        lines = []
        for a in accts:
            lines.append(
                f"- account_id {a.get('account_id')}: {a.get('account_type')} account, "
                f"balance {a.get('balance')}, status {a.get('status')}"
            )
        return "\n".join(lines)

    @staticmethod
    def _cards_summary(session_state: dict) -> str:
        cards = session_state.get("cards") or []
        if not cards:
            return "(not pre-loaded — call get_card_list first)"
        lines = []
        for c in cards:
            lines.append(
                f"- card_id {c.get('card_id')}: {c.get('card_network')} {c.get('card_type')} "
                f"ending {c.get('last_four')}, status {c.get('status')}"
            )
        return "\n".join(lines)
