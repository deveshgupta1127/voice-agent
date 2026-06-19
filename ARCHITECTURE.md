# Banking Voice Agent — Technical Specification

## Project Overview

A from-scratch voice pipeline for a banking voice agent. Three agents (Router, Card, Account) handling 4 use cases (block card, get card list, account status, stop cheque) with full streaming through WebSocket connections.

**Stack:** Python (FastAPI) backend, React (Vite) frontend, SQLite database, Sarvam Saaras v3 (STT), Sarvam Bulbul v3 (TTS), Anthropic Claude (LLM).

**Pipeline:** Browser mic → WebSocket → Sarvam STT (WebSocket, built-in VAD) → Agent System (streaming LLM + tool calls) → Sarvam TTS (WebSocket) → WebSocket → Browser speaker.

---

## Directory Structure

```
banking-voice-agent/
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── requirements.txt
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── orchestrator.py
│   │   ├── stt.py
│   │   └── tts.py
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base_agent.py
│   │   ├── router_agent.py
│   │   ├── card_agent.py
│   │   └── account_agent.py
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base_provider.py
│   │   ├── anthropic_provider.py
│   │   └── provider_factory.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── tool_registry.py
│   │   ├── verify_tools.py
│   │   ├── card_tools.py
│   │   └── account_tools.py
│   ├── database/
│   │   ├── __init__.py
│   │   ├── connection.py
│   │   ├── schema.sql
│   │   ├── seed.py
│   │   └── queries.py
│   └── utils/
│       ├── __init__.py
│       ├── logger.py
│       └── metrics.py
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── src/
│       ├── main.jsx
│       ├── App.jsx
│       ├── components/
│       │   ├── VoiceButton.jsx
│       │   ├── Transcript.jsx
│       │   ├── ToolCallPanel.jsx
│       │   ├── LatencyDashboard.jsx
│       │   └── ModelSelector.jsx
│       ├── hooks/
│       │   ├── useWebSocket.js
│       │   └── useAudioRecorder.js
│       └── utils/
│           └── audio.js
└── README.md
```

---

## Backend Specification

---

### `backend/config.py`

**Purpose:** Single source of truth for all configuration — API keys, URLs, model settings, audio parameters. Uses environment variables via python-dotenv with sensible defaults.

```python
class Settings:
    """
    Loaded once at startup. Accessed as a singleton throughout the app.
    Uses pydantic BaseSettings or a plain dataclass with os.getenv.
    """

    # API Keys
    SARVAM_API_KEY: str                    # from .env
    ANTHROPIC_API_KEY: str                 # from .env

    # Sarvam Endpoints
    SARVAM_STT_WS_URL: str = "wss://api.sarvam.ai/speech-to-text/ws"
    SARVAM_TTS_WS_URL: str = "wss://api.sarvam.ai/text-to-speech/ws"

    # Sarvam STT Settings
    STT_MODEL: str = "saaras:v3"
    STT_LANGUAGE: str = "unknown"          # auto-detect
    STT_MODE: str = "transcribe"           # transcribe | translate | verbatim
    STT_SAMPLE_RATE: int = 16000
    STT_ENCODING: str = "pcm_s16le"
    STT_HIGH_VAD_SENSITIVITY: bool = True
    STT_VAD_SIGNALS: bool = True           # receive speech_start / utterance_end

    # Sarvam TTS Settings
    TTS_MODEL: str = "bulbul:v3"
    TTS_TARGET_LANGUAGE: str = "en-IN"
    TTS_SPEAKER: str = "shubh"             # default male voice
    TTS_SAMPLE_RATE: int = 24000
    TTS_ENABLE_COMPLETION: bool = True

    # LLM Settings
    DEFAULT_LLM_PROVIDER: str = "anthropic"
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"
    LLM_MAX_TOKENS: int = 1024
    LLM_TEMPERATURE: float = 0.3          # low for banking accuracy

    # Database
    DATABASE_PATH: str = "banking.db"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WS_HEARTBEAT_INTERVAL: int = 30       # seconds


def get_settings() -> Settings:
    """Returns singleton Settings instance."""
```

---

### `backend/main.py`

**Purpose:** FastAPI application entry point. Defines the WebSocket endpoint that the browser connects to. Handles the lifecycle of a voice session — creates an orchestrator per connection, forwards audio in, sends events out.

```python
# Lifespan
async def lifespan(app: FastAPI):
    """
    Startup: Initialize database (create tables, seed if empty).
    Shutdown: Close database connection pool.
    """


# WebSocket Endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    One WebSocket connection = one voice session.

    Lifecycle:
    1. Accept connection
    2. Wait for 'start_session' message with config (llm_provider choice)
    3. Create PipelineOrchestrator with chosen provider
    4. Enter message loop:
       - Receive 'audio_chunk' messages → forward to orchestrator
       - Receive 'stop_recording' → signal end of user turn
       - Orchestrator emits events → forward to browser as JSON
    5. On disconnect: clean up orchestrator, close Sarvam connections

    Input (from browser):
        { "type": "start_session", "config": { "llm_provider": "anthropic" } }
        { "type": "audio_chunk", "data": "<base64 PCM 16kHz mono>" }
        { "type": "stop_recording" }
        { "type": "end_session" }

    Output (to browser):
        All message types defined in WebSocket Protocol section below.
    """


# Health Check
@app.get("/health")
async def health_check():
    """Returns { "status": "ok", "db": true/false }"""
```

---

### `backend/pipeline/orchestrator.py`

**Purpose:** The central coordinator. Owns one conversation session. Receives audio from the WebSocket handler, manages Sarvam STT/TTS connections, runs the agent system, and emits all events (transcripts, tool calls, latency, audio) back to the browser through a callback.

This is the most critical file — it sequences the entire turn:
1. Audio chunks arrive → forward to STT
2. STT returns transcript → emit transcript_user event, start latency timer
3. Feed transcript to agent system → stream response tokens, emit transcript_agent deltas
4. If tool calls occur → emit tool_call_start/end events
5. Agent response complete → send to TTS
6. TTS returns audio chunks → forward to browser, emit latency metrics
7. Emit turn_complete

```python
class PipelineOrchestrator:
    """
    Manages one voice conversation session end-to-end.
    """

    def __init__(
        self,
        llm_provider_name: str,        # "anthropic" — from dropdown selection
        event_callback: Callable,       # async function to send events to browser WebSocket
        settings: Settings
    ):
        """
        Creates:
        - SarvamSTT instance (not yet connected)
        - SarvamTTS instance (not yet connected)
        - LLM provider via factory
        - RouterAgent as the initial active agent
        - ConversationLogger
        - LatencyTracker
        - conversation_history: list[dict] — full message history for LLM context
        - session_state: dict — holds customer_id (once verified), current_agent, language
        """

    async def start(self) -> None:
        """
        Opens WebSocket connections to Sarvam STT and TTS.
        Sends initial config messages to both.
        Starts background task to listen for STT transcripts.
        Emits: { type: "state", state: "ready" }
        """

    async def handle_audio_chunk(self, audio_b64: str) -> None:
        """
        Receives a base64-encoded PCM audio chunk from the browser.
        Forwards it to the Sarvam STT WebSocket connection.
        Emits: { type: "state", state: "listening" }

        Input:  audio_b64: str — base64 encoded PCM 16-bit 16kHz mono
        Output: None (audio forwarded to STT)
        """

    async def _on_stt_transcript(self, transcript: str, stt_latency_ms: float) -> None:
        """
        Called when Sarvam STT returns a final transcript (after VAD detects speech end).
        This triggers the full agent processing pipeline.

        Input:
            transcript: str — the user's spoken text
            stt_latency_ms: float — processing latency reported by Sarvam

        Flow:
        1. Emit { type: "state", state: "processing" }
        2. Emit { type: "transcript_user", text: transcript }
        3. Record STT latency
        4. Call _run_agent_turn(transcript)
        """

    async def _run_agent_turn(self, user_text: str) -> None:
        """
        Runs one full agent turn: LLM reasoning + tool execution + response generation.

        Input: user_text: str — the transcribed user speech

        Flow:
        1. Add user message to conversation_history
        2. Get current active agent (router or sub-agent)
        3. Call agent.run() with conversation_history and session_state
           - This streams LLM tokens back via a callback
           - For each text delta: emit { type: "transcript_agent", text: delta, delta: true }
           - For each tool_call: emit tool_call_start, execute tool, emit tool_call_end
           - If agent returns a handover directive:
             a. Emit { type: "agent_handover", from: "router", to: "card_agent" }
             b. Switch active agent
             c. Re-run with the new agent (pass context)
        4. Collect full response text
        5. Add assistant message to conversation_history
        6. Record LLM latency (first token and total)
        7. Call _synthesize_speech(full_response_text)
        """

    async def _synthesize_speech(self, text: str) -> None:
        """
        Sends agent response text to Sarvam TTS and streams audio back to browser.

        Input: text: str — the agent's full response text

        Flow:
        1. Emit { type: "state", state: "speaking" }
        2. Send text to TTS WebSocket
        3. As audio chunks arrive from TTS:
           - Emit { type: "audio_chunk", data: "<base64 audio>" } for each chunk
        4. On TTS completion:
           - Record TTS latency
           - Emit { type: "latency", metrics: { stt_ms, llm_first_token_ms, llm_total_ms, tts_ms, total_ms } }
           - Emit { type: "turn_complete" }
           - Emit { type: "state", state: "listening" }
        """

    async def handle_stop_recording(self) -> None:
        """
        Called when user explicitly stops recording (releases button).
        Sends a flush signal to Sarvam STT to force processing any buffered audio.
        """

    async def shutdown(self) -> None:
        """
        Clean up: close STT WebSocket, close TTS WebSocket, save conversation log.
        """
```

---

### `backend/pipeline/stt.py`

**Purpose:** WebSocket client for Sarvam Saaras v3 streaming STT. Maintains a persistent WebSocket connection, forwards audio chunks, and receives transcription events (including VAD signals).

```python
class SarvamSTT:
    """
    Async WebSocket client for Sarvam speech-to-text streaming API.
    Handles connection lifecycle, audio forwarding, and transcript reception.
    """

    def __init__(
        self,
        api_key: str,
        on_transcript: Callable[[str, float], Awaitable[None]],
            # callback(transcript_text, processing_latency_ms)
        on_speech_start: Callable[[], Awaitable[None]] | None = None,
            # optional callback when VAD detects speech start
        model: str = "saaras:v3",
        language: str = "unknown",
        mode: str = "transcribe",
        sample_rate: int = 16000,
        encoding: str = "pcm_s16le",
        high_vad_sensitivity: bool = True,
        vad_signals: bool = True
    ):
        """
        Stores config. Does NOT connect yet — call connect() explicitly.
        """

    async def connect(self) -> None:
        """
        Opens WebSocket to wss://api.sarvam.ai/speech-to-text/ws
        with handshake query params:
            ?api_subscription_key={api_key}
            &model={model}
            &language={language}
            &mode={mode}
            &sample_rate={sample_rate}
            &encoding={encoding}
            &high_vad_sensitivity={high_vad_sensitivity}
            &vad_signals={vad_signals}

        Starts background task: _listen_loop()

        Raises: ConnectionError if handshake fails
        """

    async def send_audio(self, audio_b64: str) -> None:
        """
        Sends one audio chunk to Sarvam STT.

        Input:  audio_b64: str — base64-encoded PCM audio chunk
        Output: None

        Sends JSON:
        {
            "audio": {
                "data": audio_b64,
                "sample_rate": "16000",
                "encoding": "pcm_s16le"
            }
        }
        """

    async def flush(self) -> None:
        """
        Sends flush signal to force STT to process any remaining buffered audio.
        Used when user explicitly stops recording.

        Sends JSON: { "type": "flush" }
        """

    async def _listen_loop(self) -> None:
        """
        Background task: continuously reads messages from Sarvam STT WebSocket.

        Handles message types:
        1. { "type": "data", "data": { "transcript": "...", "metrics": { "processing_latency": ... } } }
           → Calls on_transcript(transcript, latency)

        2. { "type": "vad", "data": { "event": "speech_start" } }
           → Calls on_speech_start() if callback provided

        3. { "type": "vad", "data": { "event": "utterance_end" } }
           → Transcript will follow in a 'data' message

        4. { "type": "error", ... }
           → Log error, attempt reconnect if recoverable
        """

    async def close(self) -> None:
        """
        Closes the WebSocket connection gracefully.
        Cancels the _listen_loop task.
        """

    @property
    def is_connected(self) -> bool:
        """Returns True if the WebSocket is open."""
```

---

### `backend/pipeline/tts.py`

**Purpose:** WebSocket client for Sarvam Bulbul v3 streaming TTS. Sends text, receives progressive audio chunks. Handles connection lifecycle and barge-in (closing connection to stop generation).

```python
class SarvamTTS:
    """
    Async WebSocket client for Sarvam text-to-speech streaming API.
    """

    def __init__(
        self,
        api_key: str,
        on_audio_chunk: Callable[[str, str], Awaitable[None]],
            # callback(audio_b64, content_type) — called for each audio chunk
        on_complete: Callable[[], Awaitable[None]] | None = None,
            # optional callback when TTS finishes generating all audio
        model: str = "bulbul:v3",
        target_language: str = "en-IN",
        speaker: str = "shubh",
        sample_rate: int = 24000,
        enable_completion: bool = True
    ):
        """
        Stores config. Does NOT connect — call connect() explicitly.
        """

    async def connect(self) -> None:
        """
        Opens WebSocket to wss://api.sarvam.ai/text-to-speech/ws
        with handshake query params:
            ?api_subscription_key={api_key}

        Sends initial config message:
        {
            "type": "config",
            "data": {
                "model": "bulbul:v3",
                "target_language_code": "en-IN",
                "speaker": "shubh",
                "sample_rate": 24000,
                "enable_completion": true
            }
        }

        Starts background task: _listen_loop()
        """

    async def send_text(self, text: str) -> None:
        """
        Sends text for speech synthesis.

        Input:  text: str — the text to convert to speech
        Output: None

        Sends JSON:
        {
            "type": "convert",
            "data": {
                "text": text
            }
        }

        For lower barge-in latency, the orchestrator should call this
        in sentence-sized chunks rather than the full response at once.
        """

    async def flush(self) -> None:
        """
        Signals end of text input. TTS will finish generating remaining audio.

        Sends JSON: { "type": "flush" }
        """

    async def _listen_loop(self) -> None:
        """
        Background task: reads audio chunks from Sarvam TTS WebSocket.

        Handles message types:
        1. { "type": "audio", "data": { "audio": "<base64>", "content_type": "audio/wav" } }
           → Calls on_audio_chunk(audio_b64, content_type)

        2. { "type": "completion" }
           → Calls on_complete() if callback provided

        3. { "type": "error", ... }
           → Log error
        """

    async def cancel(self) -> None:
        """
        Barge-in handler: immediately closes WebSocket to stop TTS generation.
        The orchestrator calls this when VAD detects the user started speaking
        while TTS was still playing.
        Opens a new connection for the next utterance.
        """

    async def close(self) -> None:
        """Gracefully closes WebSocket connection."""

    @property
    def is_connected(self) -> bool:
        """Returns True if the WebSocket is open."""
```

---

### `backend/agents/base_agent.py`

**Purpose:** Abstract base class for all agents. Handles the common pattern: build a prompt, call the LLM with streaming, parse tool calls from the response, execute tools, and loop until the LLM returns a final text response (no more tool calls).

```python
class AgentResponse:
    """
    Returned by agent.run() after the full turn completes.
    """
    text: str                        # final response text to speak to user
    tool_calls_made: list[dict]      # [{ name, args, result, duration_ms }]
    handover: dict | None            # { "target_agent": "card_agent", "context": {...} } or None
    llm_first_token_ms: float        # latency to first token
    llm_total_ms: float              # total LLM processing time


class BaseAgent(ABC):
    """
    Abstract base class for all agents (Router, Card, Account).
    """

    def __init__(
        self,
        llm_provider: BaseLLMProvider,
        tool_registry: ToolRegistry,
        agent_name: str,              # "router" | "card_agent" | "account_agent"
    ):
        """
        Stores provider, tool registry, and agent identity.
        Each subclass defines its own system prompt and tool list.
        """

    @abstractmethod
    def get_system_prompt(self, session_state: dict) -> str:
        """
        Returns the system prompt for this agent.
        session_state includes: customer_id, language, verified (bool), etc.
        Each subclass implements its own prompt with personality, scope, instructions.

        Input:  session_state: dict
        Output: str — the system prompt
        """

    @abstractmethod
    def get_tool_names(self) -> list[str]:
        """
        Returns the list of tool names this agent is allowed to use.
        The base class uses this to filter the tool registry.

        Output: list[str] — e.g., ["get_card_list", "block_card"]
        """

    async def run(
        self,
        conversation_history: list[dict],
            # [{ "role": "user"|"assistant", "content": "..." }, ...]
        session_state: dict,
            # { "customer_id": "C001"|None, "verified": bool, "language": "hi-IN", ... }
        on_text_delta: Callable[[str], Awaitable[None]],
            # callback for each streamed text token — for live transcript
        on_tool_call_start: Callable[[str, dict], Awaitable[None]],
            # callback(tool_name, tool_args) — for tool call indicator
        on_tool_call_end: Callable[[str, dict, Any, float], Awaitable[None]],
            # callback(tool_name, tool_args, result, duration_ms)
    ) -> AgentResponse:
        """
        Runs one full agent turn with the LLM. Handles the tool-call loop.

        Flow:
        1. Build messages = [system_prompt] + conversation_history
        2. Get tool definitions for this agent's tools from registry
        3. Call llm_provider.stream(messages, tools) — streaming
        4. As text tokens arrive → call on_text_delta(token)
        5. If LLM returns tool_use blocks:
           a. For each tool call:
              - Call on_tool_call_start(name, args)
              - Execute via tool_registry.execute(name, args)
              - Call on_tool_call_end(name, args, result, duration)
           b. Append tool results to messages
           c. Call LLM again (go to step 3) — LLM sees tool results and continues
        6. When LLM returns final text (no tool calls):
           - Parse for handover directive if present
           - Return AgentResponse

        Input:
            conversation_history: list[dict] — full conversation so far
            session_state: dict — current session context
            on_text_delta: async callback for streaming text
            on_tool_call_start: async callback when tool call begins
            on_tool_call_end: async callback when tool call finishes

        Output:
            AgentResponse — contains final text, tool call log, optional handover
        """
```

---

### `backend/agents/router_agent.py`

**Purpose:** The front-door agent. Handles first contact, greeting, language detection (via Sarvam — no tool needed), identity verification, intent classification, and routing to the correct sub-agent.

```python
class RouterAgent(BaseAgent):
    """
    First agent in every conversation. Handles:
    - Greeting the user
    - Identity verification (via verify_identity tool)
    - Intent classification (built into the LLM prompt, not a tool)
    - Routing to sub-agents (via handover directive in response)
    - Handling "anything else?" follow-ups (re-classification)
    """

    def get_system_prompt(self, session_state: dict) -> str:
        """
        Returns the router agent system prompt.

        The prompt instructs the LLM to:
        1. Greet naturally in detected language
        2. If not verified: ask for mobile number, then verify with DOB/last txn
        3. If verified: classify user intent into one of:
           - "card_block" → handover to card_agent
           - "account_status" → handover to account_agent
           - "stop_cheque" → handover to account_agent
           - "out_of_scope" → inform user, offer alternatives or escalate
        4. After sub-agent completes: ask "anything else?"
        5. If user says no: end conversation

        The handover is communicated via a structured format in the LLM response:
        [HANDOVER: card_agent] or [HANDOVER: account_agent]
        The base class run() method parses this.

        Adjusts greeting and tone based on session_state["language"].

        Input:  session_state: dict
        Output: str
        """

    def get_tool_names(self) -> list[str]:
        """
        Output: ["verify_identity"]
        """
```

---

### `backend/agents/card_agent.py`

**Purpose:** Handles card-related use cases. In the POC: listing customer's cards and blocking a specific card.

```python
class CardAgent(BaseAgent):
    """
    Handles: Use Case 1 — Block lost/stolen card.

    Flow:
    1. Receives context from router (customer is already verified)
    2. Calls get_card_list to show available cards
    3. Asks user which card to block (if multiple)
    4. Asks for explicit confirmation: "Block Visa ending 4521?"
    5. On confirmation: calls block_card
    6. Reads back confirmation with reference number
    7. Returns control to router (no handover — just completes)
    """

    def get_system_prompt(self, session_state: dict) -> str:
        """
        Prompt instructs the LLM to:
        - Acknowledge the urgency ("I'll help you block your card right away")
        - Use get_card_list to fetch cards
        - If multiple cards: ask which one (read last 4 digits of each)
        - ALWAYS ask for explicit verbal confirmation before blocking
        - After blocking: read reference number, advise on replacement
        - Keep responses short — this is a phone call, not a chat

        Input:  session_state: dict (contains customer_id, language)
        Output: str
        """

    def get_tool_names(self) -> list[str]:
        """
        Output: ["get_card_list", "block_card"]
        """
```

---

### `backend/agents/account_agent.py`

**Purpose:** Handles account-related use cases. In the POC: account status check and stopping a cheque.

```python
class AccountAgent(BaseAgent):
    """
    Handles:
    - Use Case 5 — Account access issues (netbanking locked, PIN blocked, etc.)
    - Use Case 6 — Stop a cheque payment

    The LLM determines which sub-flow based on the user's intent
    (passed in conversation_history from the router).
    """

    def get_system_prompt(self, session_state: dict) -> str:
        """
        Prompt instructs the LLM to:

        For account status:
        - Call get_account_status to check for blocks/issues
        - Explain what's wrong in plain language
        - Guide user on resolution (e.g., "visit branch for KYC update")

        For stop cheque:
        - Ask for cheque number and amount
        - Call stop_cheque with confirmed details
        - Read back confirmation and reference number

        Common:
        - Keep responses concise (phone call context)
        - If the request needs human intervention → return [HANDOVER: human]

        Input:  session_state: dict (contains customer_id, language)
        Output: str
        """

    def get_tool_names(self) -> list[str]:
        """
        Output: ["get_account_status", "stop_cheque"]
        """
```

---

### `backend/llm/base_provider.py`

**Purpose:** Abstract interface for LLM providers. Any provider must support streaming responses and tool calling. This allows swapping Anthropic for Groq/Sarvam/Ollama by adding one file.

```python
class StreamEvent:
    """
    Represents one event from the LLM stream.
    """
    type: str
        # "text_delta"    — a token of text
        # "tool_use"      — LLM wants to call a tool
        # "message_end"   — stream complete
    text: str | None             # for text_delta
    tool_name: str | None        # for tool_use
    tool_args: dict | None       # for tool_use
    tool_use_id: str | None      # for tool_use — needed to return results


class BaseLLMProvider(ABC):
    """
    Abstract base class for LLM API providers.
    """

    @abstractmethod
    async def stream(
        self,
        messages: list[dict],
            # [{ "role": "system"|"user"|"assistant"|"tool", "content": ... }]
        tools: list[dict] | None = None,
            # Tool definitions in the provider's expected format
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Streams LLM response as a sequence of StreamEvents.

        Input:
            messages: list[dict] — conversation in the provider's message format
            tools: list[dict] | None — tool schemas
            temperature: float
            max_tokens: int

        Output:
            AsyncGenerator[StreamEvent] — yields events as they arrive

        Each provider implementation translates to/from its own API format.
        """

    @abstractmethod
    def format_tool_result(
        self,
        tool_use_id: str,
        result: Any
    ) -> dict:
        """
        Formats a tool execution result into the message format the provider expects.

        Input:
            tool_use_id: str — the ID from the tool_use event
            result: Any — the tool's return value (will be JSON-serialized)

        Output:
            dict — a message dict ready to append to the messages list
        """

    @abstractmethod
    def format_tool_definitions(
        self,
        tools: list[dict]
    ) -> list[dict]:
        """
        Converts our internal tool schema format into the provider's expected format.

        Input:  tools: list[dict] — [{ "name": ..., "description": ..., "parameters": {...} }]
        Output: list[dict] — provider-specific tool definitions
        """
```

---

### `backend/llm/anthropic_provider.py`

**Purpose:** Anthropic Claude implementation of the LLM provider. Uses the `anthropic` Python SDK with streaming.

```python
class AnthropicProvider(BaseLLMProvider):
    """
    Claude streaming provider using anthropic SDK.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6"
    ):
        """
        Creates an AsyncAnthropic client.
        """

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Calls client.messages.stream() with the messages and tools.

        Translates Anthropic streaming events to StreamEvent:
        - content_block_delta (type="text_delta") → StreamEvent(type="text_delta", text=delta)
        - content_block_start (type="tool_use") → StreamEvent(type="tool_use", tool_name=..., tool_args=...)
        - message_stop → StreamEvent(type="message_end")

        Tool calls: Anthropic returns tool_use content blocks with name, input (args),
        and an id. We accumulate the JSON args across deltas, then yield the complete
        tool_use event once the content block ends.
        """

    def format_tool_result(self, tool_use_id: str, result: Any) -> dict:
        """
        Returns:
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps(result)
            }]
        }
        """

    def format_tool_definitions(self, tools: list[dict]) -> list[dict]:
        """
        Converts to Anthropic tool format:
        {
            "name": "get_card_list",
            "description": "...",
            "input_schema": { "type": "object", "properties": {...}, "required": [...] }
        }
        """
```

---

### `backend/llm/provider_factory.py`

**Purpose:** Factory function that returns the right LLM provider based on a string name (from the frontend dropdown). Makes adding new providers trivial.

```python
def get_provider(provider_name: str, settings: Settings) -> BaseLLMProvider:
    """
    Factory: returns an LLM provider instance.

    Input:  provider_name: str — "anthropic" (POC only; later: "groq", "sarvam")
    Output: BaseLLMProvider instance

    Raises: ValueError if provider_name is not recognized.
    """
```

---

### `backend/tools/tool_registry.py`

**Purpose:** Central registry that maps tool names to their handler functions and schema definitions. Agents ask the registry "give me definitions for these tools" and "execute this tool with these args."

```python
class ToolDefinition:
    """
    Schema for one tool.
    """
    name: str                     # "get_card_list"
    description: str              # "Returns all cards linked to a customer"
    parameters: dict              # JSON Schema for the tool's input
    handler: Callable             # async function that executes the tool


class ToolRegistry:
    """
    Singleton registry of all available tools.
    """

    def __init__(self):
        """Initializes empty registry dict: { name: ToolDefinition }"""

    def register(self, tool_def: ToolDefinition) -> None:
        """
        Registers a tool.
        Input: tool_def: ToolDefinition
        """

    def get_definitions(self, tool_names: list[str]) -> list[dict]:
        """
        Returns tool schemas for the given names (for passing to LLM).

        Input:  tool_names: list[str] — e.g., ["get_card_list", "block_card"]
        Output: list[dict] — [{ "name": ..., "description": ..., "parameters": {...} }]
        """

    async def execute(self, tool_name: str, args: dict) -> Any:
        """
        Executes a tool by name with the given arguments.

        Input:  tool_name: str, args: dict
        Output: Any — the tool's return value (typically a dict)
        Raises: KeyError if tool_name not registered, Exception from tool execution
        """


def build_registry(db) -> ToolRegistry:
    """
    Creates and populates the tool registry with all tool definitions.
    Called once at startup.

    Input:  db — async database connection
    Output: ToolRegistry with all tools registered
    """
```

---

### `backend/tools/verify_tools.py`

**Purpose:** Identity verification tool for the Router Agent.

```python
async def verify_identity(
    db,
    mobile_number: str,
    verification_answer: str
) -> dict:
    """
    Verifies a customer's identity.

    Step 1: Look up customer by mobile number.
    Step 2: Compare verification_answer against stored DOB or last transaction amount.

    Input:
        db: async database connection
        mobile_number: str — e.g., "9876543210"
        verification_answer: str — e.g., "15-08-1990" (DOB) or "2500" (last txn amount)

    Output:
        {
            "verified": true,
            "customer_id": "C001",
            "customer_name": "Rahul Sharma"
        }
        OR
        {
            "verified": false,
            "reason": "DOB does not match" | "Customer not found"
        }

    Tool Schema:
        name: "verify_identity"
        description: "Verifies customer identity using their registered mobile number
                      and a verification answer (date of birth in DD-MM-YYYY format
                      or last transaction amount)."
        parameters:
            mobile_number: string (required) — "The customer's registered mobile number"
            verification_answer: string (required) — "Customer's DOB (DD-MM-YYYY) or last txn amount"
    """
```

---

### `backend/tools/card_tools.py`

**Purpose:** Card-related tools for the Card Agent.

```python
async def get_card_list(db, customer_id: str) -> dict:
    """
    Returns all cards linked to a customer.

    Input:
        db: database connection
        customer_id: str — e.g., "C001"

    Output:
        {
            "cards": [
                {
                    "card_id": "CARD001",
                    "card_type": "debit",          # debit | credit
                    "card_network": "Visa",        # Visa | Mastercard | RuPay
                    "last_four": "4521",
                    "status": "active",            # active | blocked | expired
                    "expiry": "12/2027"
                },
                ...
            ]
        }

    Tool Schema:
        name: "get_card_list"
        description: "Returns all debit and credit cards linked to the customer's account,
                      including card type, network, last four digits, and current status."
        parameters:
            customer_id: string (required) — "The verified customer ID"
    """


async def block_card(db, card_id: str, reason: str) -> dict:
    """
    Blocks a specific card and generates a reference number.

    Input:
        db: database connection
        card_id: str — e.g., "CARD001"
        reason: str — e.g., "lost" | "stolen" | "suspicious_activity"

    Output:
        {
            "success": true,
            "card_id": "CARD001",
            "new_status": "blocked",
            "reference_number": "BLK-20260618-001",
            "blocked_at": "2026-06-18T14:30:00Z",
            "message": "Card ending 4521 has been blocked successfully."
        }
        OR
        {
            "success": false,
            "reason": "Card is already blocked" | "Card not found"
        }

    Side effects: Updates cards table — sets status = 'blocked', blocked_at = now()

    Tool Schema:
        name: "block_card"
        description: "Blocks a debit or credit card immediately. Use this after the customer
                      has explicitly confirmed they want to block the card. Returns a
                      reference number for tracking."
        parameters:
            card_id: string (required) — "The card ID to block"
            reason: string (required) — "Reason for blocking: lost, stolen, or suspicious_activity"
    """
```

---

### `backend/tools/account_tools.py`

**Purpose:** Account-related tools for the Account Agent.

```python
async def get_account_status(db, account_id: str) -> dict:
    """
    Returns comprehensive account status including any access blocks.

    Input:
        db: database connection
        account_id: str — e.g., "ACC001"

    Output:
        {
            "account_id": "ACC001",
            "account_type": "savings",
            "status": "active",                  # active | frozen | dormant | closed
            "balance": 45230.50,
            "netbanking_status": "active",       # active | locked | not_registered
            "debit_card_pin_status": "active",   # active | blocked | not_set
            "kyc_status": "verified",            # verified | pending | expired
            "issues": [
                {
                    "type": "kyc_expiring",
                    "message": "KYC documents expire on 2026-08-15. Please visit your branch.",
                    "severity": "warning"        # info | warning | critical
                }
            ]
        }

    Tool Schema:
        name: "get_account_status"
        description: "Returns the current status of a bank account including balance,
                      netbanking status, debit card PIN status, KYC status, and any
                      active issues or blocks."
        parameters:
            account_id: string (required) — "The bank account ID"
    """


async def stop_cheque(
    db,
    account_id: str,
    cheque_number: str,
    amount: float
) -> dict:
    """
    Stops a cheque payment.

    Input:
        db: database connection
        account_id: str — e.g., "ACC001"
        cheque_number: str — e.g., "000123"
        amount: float — e.g., 15000.00

    Output:
        {
            "success": true,
            "cheque_number": "000123",
            "amount": 15000.00,
            "reference_number": "STP-20260618-001",
            "stopped_at": "2026-06-18T14:35:00Z",
            "message": "Cheque number 000123 for ₹15,000 has been stopped."
        }
        OR
        {
            "success": false,
            "reason": "Cheque already cleared" | "Cheque not found" | "Already stopped"
        }

    Side effects: Updates cheques table — sets status = 'stopped', stopped_at = now()

    Tool Schema:
        name: "stop_cheque"
        description: "Stops a cheque payment. Use after the customer confirms the cheque
                      number and amount. Returns a reference number."
        parameters:
            account_id: string (required) — "The bank account ID"
            cheque_number: string (required) — "The cheque number to stop"
            amount: number (required) — "The cheque amount for verification"
    """
```

---

### `backend/database/schema.sql`

**Purpose:** SQLite table definitions for the POC.

```sql
-- Customers: identity and verification data
CREATE TABLE IF NOT EXISTS customers (
    customer_id     TEXT PRIMARY KEY,           -- "C001"
    name            TEXT NOT NULL,              -- "Rahul Sharma"
    mobile          TEXT NOT NULL UNIQUE,       -- "9876543210"
    dob             TEXT NOT NULL,              -- "15-08-1990"
    email           TEXT,                       -- "rahul@example.com"
    language_pref   TEXT DEFAULT 'hi-IN',       -- preferred language
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Accounts: bank account information
CREATE TABLE IF NOT EXISTS accounts (
    account_id          TEXT PRIMARY KEY,       -- "ACC001"
    customer_id         TEXT NOT NULL REFERENCES customers(customer_id),
    account_type        TEXT NOT NULL,          -- "savings" | "current"
    balance             REAL NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'active',  -- active | frozen | dormant
    netbanking_status   TEXT DEFAULT 'active',  -- active | locked | not_registered
    debit_card_pin      TEXT DEFAULT 'active',  -- active | blocked | not_set
    kyc_status          TEXT DEFAULT 'verified',-- verified | pending | expired
    kyc_expiry          TEXT,                   -- date
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Cards: debit and credit cards
CREATE TABLE IF NOT EXISTS cards (
    card_id         TEXT PRIMARY KEY,           -- "CARD001"
    customer_id     TEXT NOT NULL REFERENCES customers(customer_id),
    account_id      TEXT REFERENCES accounts(account_id),
    card_type       TEXT NOT NULL,              -- "debit" | "credit"
    card_network    TEXT NOT NULL,              -- "Visa" | "Mastercard" | "RuPay"
    last_four       TEXT NOT NULL,              -- "4521"
    status          TEXT NOT NULL DEFAULT 'active',  -- active | blocked | expired
    blocked_reason  TEXT,                       -- null | "lost" | "stolen" | "suspicious_activity"
    blocked_at      TEXT,                       -- timestamp when blocked
    block_ref       TEXT,                       -- reference number for blocking
    expiry          TEXT NOT NULL,              -- "12/2027"
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Cheques: cheque book records
CREATE TABLE IF NOT EXISTS cheques (
    cheque_id       TEXT PRIMARY KEY,           -- "CHQ001"
    account_id      TEXT NOT NULL REFERENCES accounts(account_id),
    cheque_number   TEXT NOT NULL,              -- "000123"
    amount          REAL,                       -- 15000.00
    payee           TEXT,                       -- "Acme Corp"
    status          TEXT NOT NULL DEFAULT 'issued', -- issued | cleared | stopped | bounced
    stopped_at      TEXT,                       -- timestamp when stopped
    stop_ref        TEXT,                       -- reference number
    issued_at       TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Transactions: recent transaction records (for verify_identity via last txn)
CREATE TABLE IF NOT EXISTS transactions (
    txn_id          TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES accounts(account_id),
    amount          REAL NOT NULL,
    txn_type        TEXT NOT NULL,              -- "credit" | "debit"
    description     TEXT,
    status          TEXT DEFAULT 'completed',   -- completed | pending | failed | reversed
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
```

---

### `backend/database/connection.py`

**Purpose:** Async SQLite connection management using aiosqlite.

```python
_db: aiosqlite.Connection | None = None

async def init_db(db_path: str) -> aiosqlite.Connection:
    """
    Opens async SQLite connection. Enables WAL mode and foreign keys.
    Runs schema.sql to create tables if they don't exist.
    Calls seed_database() if tables are empty.

    Input:  db_path: str — path to SQLite file
    Output: aiosqlite.Connection
    """

async def get_db() -> aiosqlite.Connection:
    """
    Returns the current database connection.
    Raises RuntimeError if init_db hasn't been called.

    Output: aiosqlite.Connection
    """

async def close_db() -> None:
    """Closes the database connection."""
```

---

### `backend/database/seed.py`

**Purpose:** Populates the database with realistic mock data for testing.

```python
async def seed_database(db: aiosqlite.Connection) -> None:
    """
    Inserts mock data into all tables if they're empty.

    Creates:
    - 3 customers (with Indian names, valid mobile numbers, DOBs)
    - 4 accounts (mix of savings/current, one frozen, one with expired KYC)
    - 6 cards (mix of debit/credit, Visa/Mastercard/RuPay, one already blocked)
    - 4 cheques (mix of issued/cleared, one already stopped)
    - 10 transactions (recent, mix of credit/debit, one failed)

    The data is designed to exercise all tool paths:
    - Customer C001 has 2 cards (one active, one already blocked) → tests block_card happy + failure
    - Customer C002 has a frozen account → tests get_account_status with issues
    - Cheque CHQ002 is already cleared → tests stop_cheque failure case
    """
```

---

### `backend/database/queries.py`

**Purpose:** Typed async query functions. Every database access goes through here — tools never write raw SQL.

```python
async def get_customer_by_mobile(db, mobile: str) -> dict | None:
    """
    Input:  mobile: str — "9876543210"
    Output: { "customer_id", "name", "mobile", "dob", ... } or None
    """

async def get_cards_by_customer(db, customer_id: str) -> list[dict]:
    """
    Input:  customer_id: str
    Output: [{ "card_id", "card_type", "card_network", "last_four", "status", "expiry" }]
    """

async def update_card_status(
    db,
    card_id: str,
    status: str,
    reason: str,
    reference: str
) -> bool:
    """
    Input:  card_id, status ("blocked"), reason, reference number
    Output: True if updated, False if card not found
    Side effects: Updates cards table
    """

async def get_account(db, account_id: str) -> dict | None:
    """
    Input:  account_id: str
    Output: { "account_id", "account_type", "balance", "status",
              "netbanking_status", "debit_card_pin", "kyc_status", "kyc_expiry" } or None
    """

async def get_accounts_by_customer(db, customer_id: str) -> list[dict]:
    """
    Input:  customer_id: str
    Output: list of account dicts
    """

async def get_cheque(db, account_id: str, cheque_number: str) -> dict | None:
    """
    Input:  account_id, cheque_number
    Output: { "cheque_id", "cheque_number", "amount", "payee", "status" } or None
    """

async def update_cheque_status(
    db,
    cheque_id: str,
    status: str,
    reference: str
) -> bool:
    """
    Input:  cheque_id, status ("stopped"), reference number
    Output: True if updated, False if not found
    Side effects: Updates cheques table
    """

async def get_last_transaction(db, account_id: str) -> dict | None:
    """
    Input:  account_id: str
    Output: { "amount", "txn_type", "description", "created_at" } or None
    Used by verify_identity to check last transaction amount.
    """
```

---

### `backend/utils/metrics.py`

**Purpose:** Per-turn latency tracking. Timestamps each pipeline stage and computes durations.

```python
class LatencyTracker:
    """
    Tracks latency for one conversation turn.
    Supports nested timing (e.g., multiple tool calls within one LLM turn).
    """

    def __init__(self):
        """Initializes with empty timestamps dict."""

    def mark(self, event_name: str) -> None:
        """
        Records current timestamp for a named event.

        Input: event_name: str — e.g., "stt_start", "stt_end", "llm_first_token", "tts_start"
        """

    def get_metrics(self) -> dict:
        """
        Computes all latency metrics from recorded timestamps.

        Output:
        {
            "stt_ms": float,              # stt_end - stt_start
            "llm_first_token_ms": float,  # llm_first_token - llm_start
            "llm_total_ms": float,        # llm_end - llm_start
            "tts_first_chunk_ms": float,  # tts_first_chunk - tts_start
            "tts_total_ms": float,        # tts_end - tts_start
            "total_ms": float,            # tts_end - stt_start (end-to-end)
            "tool_calls_ms": float        # sum of all tool call durations
        }
        """

    def reset(self) -> None:
        """Clears all timestamps for the next turn."""
```

---

### `backend/utils/logger.py`

**Purpose:** Structured per-turn conversation logging. Logs every turn with transcript, tool calls, latency, and agent info. Outputs to console (structured) and optionally to a JSON log file.

```python
class ConversationLogger:
    """
    Logs every conversation turn as a structured record.
    """

    def __init__(self, session_id: str):
        """Creates logger for a specific session."""

    def log_turn(
        self,
        turn_number: int,
        user_text: str,
        agent_name: str,
        agent_response: str,
        tool_calls: list[dict],
        metrics: dict,
        handover: dict | None = None
    ) -> None:
        """
        Logs one complete turn.

        Input:
            turn_number: int
            user_text: str — STT transcript
            agent_name: str — which agent handled this turn
            agent_response: str — full agent response text
            tool_calls: [{ "name", "args", "result", "duration_ms" }]
            metrics: { "stt_ms", "llm_first_token_ms", ... }
            handover: { "from", "to" } or None

        Output: Prints structured log, appends to session log list.
        """

    def log_error(self, stage: str, error: str) -> None:
        """
        Logs an error with which pipeline stage it occurred in.
        Input: stage: str ("stt"|"llm"|"tts"|"tool"), error: str
        """

    def get_full_log(self) -> list[dict]:
        """Returns the complete session log for export."""
```

---

## Frontend Specification

---

### `frontend/src/App.jsx`

**Purpose:** Root component. Manages all top-level state and passes it down to children. Owns the WebSocket connection via hook.

```jsx
function App() {
    /**
     * State:
     *   sessionState: "idle" | "connecting" | "ready" | "listening" | "processing" | "speaking"
     *   transcriptEntries: [{ role: "user"|"agent", text: str, timestamp: Date }]
     *   toolCalls: [{ name, args, result, status: "running"|"complete", duration_ms }]
     *   latencyMetrics: { stt_ms, llm_first_token_ms, tts_ms, total_ms } | null
     *   selectedModel: "anthropic"
     *   currentAgent: "router" | "card_agent" | "account_agent"
     *   agentStreamText: str  — accumulates agent text deltas for current turn
     *
     * WebSocket message handler:
     *   Receives messages from backend, updates state based on type:
     *   - "state"            → update sessionState
     *   - "transcript_user"  → append to transcriptEntries
     *   - "transcript_agent" → if delta: append to agentStreamText (live typing effect)
     *                          if not delta: finalize as a transcript entry
     *   - "tool_call_start"  → add to toolCalls with status "running"
     *   - "tool_call_end"    → update matching tool call with result + "complete"
     *   - "agent_handover"   → update currentAgent, optionally show in transcript
     *   - "audio_chunk"      → pass to audio playback queue
     *   - "latency"          → update latencyMetrics
     *   - "turn_complete"    → finalize agentStreamText into transcript entry, clear tool calls
     *
     * Renders:
     *   <ModelSelector />
     *   <VoiceButton />
     *   <Transcript />
     *   <ToolCallPanel />
     *   <LatencyDashboard />
     */
}
```

---

### `frontend/src/components/ModelSelector.jsx`

**Purpose:** Dropdown to select the LLM provider. Sends choice with start_session message. Disabled during active session.

```jsx
function ModelSelector({ selectedModel, onModelChange, disabled }) {
    /**
     * Props:
     *   selectedModel: str — "anthropic"
     *   onModelChange: (model: str) => void
     *   disabled: bool — true when session is active
     *
     * Renders:
     *   <select> with options:
     *     - "anthropic" → "Claude (Anthropic)" — only option for POC
     *     - Future: "groq", "sarvam-100b", "sarvam-30b"
     *
     * Emits: onModelChange(selectedValue) on change
     */
}
```

---

### `frontend/src/components/VoiceButton.jsx`

**Purpose:** The main interaction element. Click to start session and begin recording, click again to stop. Visual states: idle, connecting, listening (pulsing), processing (spinner), speaking (waveform animation).

```jsx
function VoiceButton({ sessionState, onStartSession, onStopRecording }) {
    /**
     * Props:
     *   sessionState: "idle"|"connecting"|"ready"|"listening"|"processing"|"speaking"
     *   onStartSession: () => void — called on first click (connects + starts recording)
     *   onStopRecording: () => void — called when user clicks to stop recording
     *
     * Visual states:
     *   "idle"        → mic icon, "Click to start", neutral color
     *   "connecting"  → spinner, "Connecting..."
     *   "ready"       → mic icon, "Click to speak", ready color
     *   "listening"   → pulsing animation, "Listening...", active color
     *   "processing"  → loading spinner, "Processing..."
     *   "speaking"    → waveform animation, "Agent speaking..."
     *
     * Behavior:
     *   Click when idle → onStartSession()
     *   Click when ready → start recording (via useAudioRecorder)
     *   Click when listening → stop recording, call onStopRecording()
     *   Click when processing/speaking → ignored (or triggers barge-in later)
     */
}
```

---

### `frontend/src/components/Transcript.jsx`

**Purpose:** Live transcript panel showing both user and agent messages. Agent messages stream in word-by-word (from text deltas). Shows agent name labels.

```jsx
function Transcript({ entries, agentStreamText, currentAgent }) {
    /**
     * Props:
     *   entries: [{ role: "user"|"agent", text: str, timestamp: Date, agent?: str }]
     *   agentStreamText: str — current agent response being streamed (shows live typing)
     *   currentAgent: str — name of currently active agent (shown as label)
     *
     * Renders:
     *   Scrollable container, auto-scrolls to bottom.
     *   Each entry:
     *     - User messages: right-aligned, user bubble style, prefixed "You"
     *     - Agent messages: left-aligned, agent bubble style, prefixed with agent name
     *   If agentStreamText is non-empty:
     *     - Shows it as a typing/streaming bubble with blinking cursor at end
     *     - Agent name label shown above
     */
}
```

---

### `frontend/src/components/ToolCallPanel.jsx`

**Purpose:** Visual indicators for tool calls. Shows which tool was called, with what arguments, and its result. Running tools show a spinner; completed ones show a checkmark.

```jsx
function ToolCallPanel({ toolCalls }) {
    /**
     * Props:
     *   toolCalls: [{
     *     name: str,             — "get_card_list"
     *     args: dict,            — { customer_id: "C001" }
     *     result: dict | null,   — null while running
     *     status: "running" | "complete",
     *     duration_ms: number | null
     *   }]
     *
     * Renders:
     *   Collapsible panel (or sidebar section).
     *   Each tool call as a card:
     *     - Tool name in monospace font
     *     - Args as key-value pairs
     *     - Status icon: spinner (running) or checkmark (complete)
     *     - Result (collapsed/expandable) when complete
     *     - Duration badge: "45ms"
     *   Empty state: "No tool calls yet"
     *   Clears on turn_complete.
     */
}
```

---

### `frontend/src/components/LatencyDashboard.jsx`

**Purpose:** Real-time display of per-stage latency metrics. Updates after each turn.

```jsx
function LatencyDashboard({ metrics }) {
    /**
     * Props:
     *   metrics: {
     *     stt_ms: number,
     *     llm_first_token_ms: number,
     *     llm_total_ms: number,
     *     tts_first_chunk_ms: number,
     *     tts_total_ms: number,
     *     total_ms: number,
     *     tool_calls_ms: number
     *   } | null
     *
     * Renders:
     *   Horizontal bar chart or segmented bar showing:
     *     [STT: 320ms] [LLM first token: 180ms] [TTS: 290ms] = Total: 790ms
     *   Each segment color-coded.
     *   Shows "—" or empty state when metrics is null.
     *   Optionally: history of last N turns as a mini-chart to spot trends.
     */
}
```

---

### `frontend/src/hooks/useWebSocket.js`

**Purpose:** Custom hook managing the WebSocket connection to the backend. Handles connect, disconnect, reconnect, and message dispatch.

```javascript
function useWebSocket(url) {
    /**
     * Input: url: string — "ws://localhost:8000/ws"
     *
     * Returns: {
     *   connect: () => void,
     *       — opens WebSocket connection
     *
     *   disconnect: () => void,
     *       — closes WebSocket connection
     *
     *   sendMessage: (message: object) => void,
     *       — JSON-serializes and sends a message
     *       — e.g., sendMessage({ type: "audio_chunk", data: base64 })
     *
     *   isConnected: boolean,
     *       — current connection state
     *
     *   onMessage: (callback: (data: object) => void) => void,
     *       — registers a handler for incoming messages
     *       — the hook parses JSON and calls the callback with the parsed object
     *
     *   lastError: string | null
     *       — last error message for display
     * }
     *
     * Internal behavior:
     *   - Auto-reconnect with exponential backoff on unexpected close
     *   - Heartbeat ping every 30s to keep connection alive
     *   - Queues messages sent while disconnected (optional)
     */
}
```

---

### `frontend/src/hooks/useAudioRecorder.js`

**Purpose:** Custom hook for capturing microphone audio, converting to PCM 16-bit 16kHz mono, and streaming chunks via a callback. Uses the Web Audio API (AudioContext, MediaStreamSource, ScriptProcessorNode/AudioWorklet).

```javascript
function useAudioRecorder(onAudioChunk) {
    /**
     * Input:
     *   onAudioChunk: (base64PcmChunk: string) => void
     *       — called every ~100ms with a base64-encoded PCM chunk
     *       — the App sends this to the backend via WebSocket
     *
     * Returns: {
     *   startRecording: () => Promise<void>,
     *       — requests mic permission, starts capturing
     *       — sets up AudioContext at 16kHz (or resamples from native rate)
     *       — begins calling onAudioChunk with PCM data
     *
     *   stopRecording: () => void,
     *       — stops capturing, releases mic
     *       — stops calling onAudioChunk
     *
     *   isRecording: boolean,
     *       — current recording state
     *
     *   error: string | null
     *       — mic permission denied, etc.
     * }
     *
     * Audio format produced:
     *   - PCM 16-bit signed little-endian
     *   - 16000 Hz sample rate (what Sarvam expects)
     *   - Mono (single channel)
     *   - Chunked every ~100ms (~3200 bytes per chunk at 16kHz × 16-bit)
     *   - Base64 encoded for JSON transport
     *
     * Implementation notes:
     *   - Browser mic usually captures at 44.1kHz or 48kHz
     *   - Must downsample to 16kHz before sending
     *   - Use AudioContext with sampleRate: 16000 (Chrome supports this)
     *     OR capture at native rate and resample via linear interpolation
     *   - Convert Float32 samples to Int16 PCM
     */
}
```

---

### `frontend/src/utils/audio.js`

**Purpose:** Audio utility functions for PCM encoding and playback queue management.

```javascript
/**
 * Converts Float32Array audio samples to base64-encoded PCM 16-bit LE.
 *
 * Input:  float32Array: Float32Array — samples in [-1.0, 1.0]
 * Output: string — base64-encoded PCM bytes
 */
function float32ToPcm16Base64(float32Array) {}


/**
 * Decodes base64 audio data and queues it for playback.
 * Manages a sequential playback queue so chunks play in order without gaps.
 *
 * Uses AudioContext to decode and play audio buffers.
 */
class AudioPlaybackQueue {
    constructor(sampleRate = 24000) {}
        // sampleRate: number — Sarvam TTS outputs at 24kHz

    enqueue(audioBase64, contentType) {}
        // Input: audioBase64: string, contentType: string (e.g., "audio/wav")
        // Decodes and adds to playback queue

    play() {}
        // Starts playing queued audio sequentially

    stop() {}
        // Stops playback immediately, clears queue (for barge-in)

    get isPlaying() {}
        // Returns: boolean
}
```

---

## WebSocket Message Protocol — Complete Reference

### Browser → Backend

| Type | Payload | When |
|------|---------|------|
| `start_session` | `{ config: { llm_provider: "anthropic" } }` | User clicks start |
| `audio_chunk` | `{ data: "<base64 PCM>" }` | Every ~100ms while recording |
| `stop_recording` | `{}` | User clicks stop / releases button |
| `end_session` | `{}` | User explicitly ends conversation |

### Backend → Browser

| Type | Payload | Purpose |
|------|---------|---------|
| `state` | `{ state: "ready"\|"listening"\|"processing"\|"speaking" }` | Pipeline state → drives VoiceButton visual |
| `transcript_user` | `{ text: "mera card block karo" }` | STT result → Transcript panel |
| `transcript_agent` | `{ text: "I'll", delta: true }` | Streamed LLM token → live typing in Transcript |
| `transcript_agent` | `{ text: "I'll help you block...", delta: false }` | Final complete response |
| `agent_handover` | `{ from: "router", to: "card_agent" }` | Agent switch → label change in Transcript |
| `tool_call_start` | `{ name: "get_card_list", args: { customer_id: "C001" } }` | Tool invoked → ToolCallPanel spinner |
| `tool_call_end` | `{ name: "get_card_list", result: {...}, duration_ms: 45 }` | Tool done → ToolCallPanel checkmark |
| `audio_chunk` | `{ data: "<base64 audio>", content_type: "audio/wav" }` | TTS audio → AudioPlaybackQueue |
| `latency` | `{ metrics: { stt_ms, llm_first_token_ms, tts_ms, total_ms } }` | Turn done → LatencyDashboard |
| `turn_complete` | `{}` | Turn finished → reset tool calls, finalize transcript |
| `error` | `{ stage: "stt"\|"llm"\|"tts", message: "..." }` | Error → display in UI |

---

## Build Order

This is the order in which files should be built, each step testable before moving on:

1. **`config.py`** — set up env loading, verify API keys exist
2. **`database/schema.sql` → `connection.py` → `seed.py` → `queries.py`** — build and verify with a test script
3. **`tools/verify_tools.py` → `card_tools.py` → `account_tools.py` → `tool_registry.py`** — test tools against seeded DB
4. **`llm/base_provider.py` → `anthropic_provider.py` → `provider_factory.py`** — test streaming with a simple prompt
5. **`agents/base_agent.py` → `router_agent.py` → `card_agent.py` → `account_agent.py`** — test agent loop with text input (no audio)
6. **`pipeline/stt.py`** — test Sarvam STT WebSocket independently with a WAV file
7. **`pipeline/tts.py`** — test Sarvam TTS WebSocket independently with a text string
8. **`pipeline/orchestrator.py`** — wire everything together
9. **`main.py`** — WebSocket endpoint, test with a simple WebSocket client
10. **Frontend: `useWebSocket.js` → `useAudioRecorder.js` → `audio.js`** — test mic capture and playback
11. **Frontend: `App.jsx` + all components** — connect to backend, full end-to-end test
12. **`utils/metrics.py` → `logger.py`** — add observability, verify latency numbers show in dashboard
