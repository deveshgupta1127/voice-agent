# Banking Voice Agent - Changes, Design Decisions & Tradeoffs

## Table of Contents

1. [Project Foundation](#1-project-foundation)
2. [Voice Activity Detection (Client-Side VAD)](#2-voice-activity-detection-client-side-vad)
3. [Session-Based Structured Logging](#3-session-based-structured-logging)
4. [End-Session Handling & Agent Context Transfer](#4-end-session-handling--agent-context-transfer)
5. [Barge-In Handling](#5-barge-in-handling)
6. [Multi-Provider LLM Support](#6-multi-provider-llm-support)
7. [Barge-In State Machine Refinement](#7-barge-in-state-machine-refinement)
8. [Subsentence TTS Chunking](#8-subsentence-tts-chunking)
9. [Transaction & Payment Agents](#9-transaction--payment-agents)
10. [Escalation to Human Agent](#10-escalation-to-human-agent)
11. [Identity Verification System](#11-identity-verification-system)
12. [Mandatory Reason Collection for Sensitive Actions](#12-mandatory-reason-collection-for-sensitive-actions)
13. [Language Detection & Multilingual Pipeline](#13-language-detection--multilingual-pipeline)
14. [Silent Agent Handover](#14-silent-agent-handover)
15. [RAG Pipeline for General Q&A](#15-rag-pipeline-for-general-qa)
16. [TTS Bracket Directive Stripping](#16-tts-bracket-directive-stripping)
17. [Persistent WebSocket TTS Connection](#17-persistent-websocket-tts-connection)
18. [Dual STT Path (Streaming + Batch Fallback)](#18-dual-stt-path-streaming--batch-fallback)
19. [Latency Tracking & Metrics Dashboard](#19-latency-tracking--metrics-dashboard)
20. [Database Design for Edge-Case Testing](#20-database-design-for-edge-case-testing)
21. [Known Issues](#21-known-issues)

---

## 1. Project Foundation

**Commit:** `c702e5a` - *first commit*

Built the core architecture: a WebSocket-based voice pipeline connecting a React frontend to a FastAPI backend with a multi-agent system, SQLite database, and pluggable LLM providers.

### Architecture

```
Browser (React + Web Audio API)
   │
   │  WebSocket (persistent, full-duplex)
   │
FastAPI Server
   ├── PipelineOrchestrator (turn management)
   │     ├── STT: Sarvam Saaras v3 (WebSocket streaming)
   │     ├── LLM: Anthropic Claude / Sarvam (streaming)
   │     └── TTS: Sarvam Bulbul v3 (WebSocket streaming)
   ├── Agent System
   │     ├── RouterAgent (entry point, verification, routing)
   │     ├── CardAgent (card listing, blocking)
   │     └── AccountAgent (account status, stop cheque)
   ├── Tool Registry (maps tool names to functions)
   ├── SQLite Database (customers, accounts, cards, cheques)
   └── Logging + Metrics
```

### What was chosen

- **WebSocket** for browser-server communication instead of REST polling or WebRTC
- **Sarvam AI** for STT and TTS (Indian language-first, WebSocket-native APIs)
- **Anthropic Claude Haiku** as default LLM for tool calling accuracy
- **SQLite** as the database
- **Agent-per-domain** pattern with a central router

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| WebSocket | WebRTC data channels | WebSocket is simpler to implement, works through all proxies, and is sufficient for sequential audio streaming | No peer-to-peer capability; all audio must route through the server. WebRTC would allow direct browser-to-STT connections and lower latency |
| WebSocket | REST with polling / SSE | WebSocket gives true bidirectional streaming; REST would require separate upload and polling endpoints | WebSocket connections are stateful and harder to load-balance across servers. REST would be simpler to scale horizontally |
| Sarvam STT/TTS | Google Cloud Speech / Amazon Polly / Azure Speech | Sarvam has first-class support for Indian languages (Hindi, Tamil, Telugu, etc.) and WebSocket streaming. Google/Azure would need extra config for Indic language accuracy | Vendor lock-in to a smaller provider. Google/Azure have broader language coverage, more mature SDKs, and better uptime SLAs |
| Sarvam STT/TTS | Whisper (local) + Coqui TTS | Local models eliminate API costs and network latency entirely | Requires GPU hardware. Whisper's Indic language accuracy is weaker than Sarvam's specialized models. Coqui has limited Indian voice quality |
| Claude Haiku | GPT-4o-mini / Gemini Flash | Claude Haiku has strong tool-calling reliability and follows complex system prompts accurately | Anthropic API costs more per token than some alternatives. GPT-4o-mini is cheaper but less reliable at multi-step tool sequences |
| SQLite | PostgreSQL / MySQL | Zero-config, file-based, perfect for a demo/prototype with <100 concurrent users | No concurrent write support. Cannot scale to production multi-server deployment without switching to a client-server database |
| Agent-per-domain | Single monolithic agent with all tools | Smaller, focused system prompts per agent improve instruction following and reduce hallucination | Extra latency from handover turns. Conversation history shared across agents can confuse context boundaries |
| Agent-per-domain | LangGraph / CrewAI / AutoGen framework | Custom implementation gives full control over handover logic, streaming, and latency | No built-in retry logic, memory management, or observability that frameworks provide. More code to maintain |

**Files:** `backend/main.py`, `backend/config.py`, `backend/pipeline/orchestrator.py`, `backend/agents/router_agent.py`, `backend/agents/base_agent.py`, `backend/agents/card_agent.py`, `backend/agents/account_agent.py`, `backend/tools/tool_registry.py`, `backend/database/`

---

## 2. Voice Activity Detection (Client-Side VAD)

**Commit:** `9f69873` - *vad added. now able to detect voice on it's own*

Replaced the push-to-talk model with automatic speech detection using the Web Audio API. The system continuously monitors microphone input and detects when the user starts and stops speaking without any button press.

### How it works

- Uses RMS energy levels with hysteresis: speech start threshold at `0.025`, silence detection at `0.015` (the gap prevents rapid toggling)
- Tracks a 4-state machine: `silence` -> `speech` -> `trailing_silence` -> `ended`
- Maintains a rolling pre-buffer of 4 audio chunks (~1 second) so the beginning of speech is never clipped
- 1500ms silence window before finalizing utterance end
- Minimum speech duration of 250ms filters out short noise bursts
- VAD can be paused during processing and resumed when ready for next input

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| Client-side energy-based VAD | Server-side VAD (Sarvam's built-in) | Immediate detection without network round-trip. User sees instant visual feedback when speech is detected | Energy-based VAD is noise-sensitive. A cough, door slam, or background music can trigger false positives. Server-side VAD uses ML models that distinguish speech from noise more accurately |
| Client-side energy-based VAD | WebRTC VAD / `@ricky0123/vad-web` (Silero VAD in browser) | Simple implementation with no additional dependencies. Energy-based VAD is predictable and easy to tune | Silero VAD is a neural network trained specifically for speech detection; it handles background noise, music, and non-speech sounds far better. The tradeoff is ~2MB model download and WASM runtime overhead |
| Client-side energy-based VAD | Push-to-talk button | PTT is 100% accurate for speech boundary detection — no false starts, no premature cutoffs | Terrible UX for a voice agent. Users expect natural conversation. PTT also makes the product inaccessible for hands-free use cases |
| 1500ms silence timeout | Shorter (500ms) or longer (3000ms) | Balances responsiveness with natural speech pauses. Most conversational pauses are under 1 second | Too short: cuts off users mid-sentence when they pause to think. Too long: adds 1.5s of dead time before the agent starts responding. Number dictation (phone numbers, amounts) is particularly affected — users naturally pause between digit groups |
| ScriptProcessor node | AudioWorklet | ScriptProcessor was faster to implement and works in all browsers including older ones | ScriptProcessor runs on the main thread (deprecated API). Heavy UI rendering causes audio timing jitter. AudioWorklet runs in a separate thread with guaranteed timing |
| 4-chunk pre-buffer | No pre-buffer / larger buffer | 4 chunks (~1 second) captures the typical onset of speech without sending too much silence to STT | Pre-buffer includes ambient noise that gets transcribed as artifacts. A larger buffer would send even more noise. No buffer would clip the first syllable of speech |

**Files:** `frontend/src/hooks/useAudioRecorder.js`

---

## 3. Session-Based Structured Logging

**Commit:** `ef4466f` - *server based and session based logging added*

Added per-session JSON log files and CSV-based latency metrics tracking so every conversation can be replayed and analyzed.

### What was added

- Each session gets its own JSON file at `backend/logs/sessions/<session_id>.json`
- Logs contain per-turn data: user transcript, agent name, agent response, tool calls, latency metrics, handover events
- Latency metrics written to a shared CSV file for offline analysis
- Console logging with configurable levels (DEBUG to file, INFO to console)

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| JSON files per session | Structured logging to a database (ClickHouse, Elasticsearch) | Zero infrastructure. Easy to inspect individual sessions by reading a file | No querying across sessions. Cannot answer "how many sessions had >2s latency last week" without parsing all files. No real-time monitoring |
| CSV latency file | Time-series database (InfluxDB, Prometheus + Grafana) | Single file, no external dependencies. Can be opened in Excel for quick analysis | CSV appending is not concurrent-safe. No alerting, dashboards, or retention policies. Grows unbounded |
| File-based logs | Cloud logging (CloudWatch, Datadog, OpenTelemetry) | Works offline, no API keys needed, no cost | No centralized view, no alerting, no correlation with infrastructure metrics |

**Files:** `backend/utils/logger.py`, `backend/utils/metrics.py`

---

## 4. End-Session Handling & Agent Context Transfer

**Commit:** `41e70c2` - *end session resolved, agent context transfer handled*

Fixed the session teardown flow and improved how conversation context transfers between agents during handovers.

### What was fixed

- Proper cleanup of WebSocket connections, STT/TTS sockets, and session state on session end
- Conversation history is shared as a single list across all agents — when a handover occurs, the new agent sees the full prior conversation without any explicit state copying
- Session state (customer_id, verified status, language, accounts, cards) persists across agent switches
- Prevented dangling sessions when the browser closes without sending `end_session`

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| Shared conversation history list | Per-agent isolated history with summary handoff | Full context available to every agent. No information loss during handover | Token usage grows linearly with conversation length since every agent sees everything. Agents may get confused by tool calls meant for a different specialist |
| Shared conversation history list | Event-sourced state with agent-specific views | Simpler implementation. No serialization/deserialization overhead | Cannot filter history per agent. A card agent sees transaction dispute context it doesn't need, potentially confusing the LLM |
| Bounded history (16 messages) | Unbounded history / sliding window with summarization | Hard cap keeps token costs predictable and prevents context window overflow | Long conversations lose early context. If a customer mentions something important in turn 1 and it scrolls out by turn 9, the agent forgets it |

**Files:** `backend/pipeline/orchestrator.py`, `backend/agents/base_agent.py`, `backend/tools/verify_tools.py`

---

## 5. Barge-In Handling

**Commit:** `f7dd052` - *barge in handling added from server side*

Users can now interrupt the agent mid-speech. When the VAD detects speech while the agent is talking, the system stops audio playback, cancels the ongoing pipeline, and starts listening to the user.

### How it works

- Client-side: stops the audio playback queue and sends a `barge_in` event over WebSocket
- Server-side: cancels the running `asyncio.Task` for the current turn (in-flight LLM streaming and TTS synthesis)
- Partial agent responses are saved to conversation history with an `[interrupted by customer]` marker
- If the agent hadn't started responding yet, history records `[interrupted before responding]`

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| Cancel-and-restart on barge-in | Queue user input while agent finishes | Natural conversation flow. Users don't have to wait for the agent to finish a wrong or long answer | Any in-flight TTS API calls are wasted (paid for but results discarded). Agent's partial response is permanently lost — cannot be resumed |
| Cancel-and-restart on barge-in | Pause agent, process interruption, then decide whether to resume | Would allow "wait, go back" style interactions | Much more complex state management. Requires buffering the paused agent state and LLM continuation, which most providers don't support mid-stream |
| `asyncio.Task.cancel()` | Cooperative cancellation with flags | Immediate termination of all in-flight work | Can leave resources in inconsistent state if cancellation hits during a database write or mid-tool-execution. asyncio cancellation doesn't propagate to external HTTP/WebSocket connections cleanly |
| `[interrupted by customer]` marker | No marker / separate metadata field | LLM can see that its previous response was cut short and adjust (e.g., not repeat the same opening) | The marker is visible in the system prompt context and consumes tokens. LLM might over-index on the interruption and apologize unnecessarily |

**Files:** `frontend/src/App.jsx`, `backend/pipeline/orchestrator.py`

---

## 6. Multi-Provider LLM Support

**Commits:** `6965b36` - *sarvam 30b params model added*, `5ee412b` - *sarvam 105b model added*

Added support for three LLM providers switchable from a frontend dropdown: Anthropic Claude Haiku 4.5, Sarvam 30B, and Sarvam 105B.

### How it works

- All providers implement `BaseLLMProvider` with a `stream_response(messages, tools, system_prompt)` interface
- Provider factory instantiates the correct provider based on the selected model string
- Frontend `ModelSelector` component sends the chosen provider during `start_session`
- Sarvam providers use their own API endpoint with streaming; Anthropic uses the official SDK

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| Runtime provider switching via dropdown | Environment variable / config file only | Lets users A/B test providers in real-time without restarting the server | More complex error handling — each provider has different failure modes, rate limits, and tool-calling formats. A provider that works in testing might fail differently in production |
| Custom provider abstraction | LiteLLM / LangChain LLM wrapper | Minimal dependencies, full control over streaming and tool-call parsing | Must maintain provider-specific code for each new LLM. LiteLLM handles 100+ providers with a unified interface and automatic retries |
| Sarvam 30B + 105B | Only Anthropic / only one Sarvam model | Sarvam models are specifically trained for Indian languages — better Hindi/regional language responses. Two sizes give a speed vs quality tradeoff | Sarvam models have weaker tool-calling reliability compared to Claude. The 105B model is slower and more expensive but gives better reasoning. Users need to understand which model to pick |
| Claude Haiku as default | Claude Sonnet / Opus | Haiku is the fastest Claude model with reliable tool calling — critical for a voice agent where every 100ms matters | Haiku has weaker reasoning than Sonnet for complex multi-step queries. But for banking tasks (structured tool calls, simple routing), Haiku is sufficient |

**Files:** `backend/llm/provider_factory.py`, `backend/llm/sarvam_provider.py`, `backend/llm/anthropic_provider.py`, `backend/llm/base_provider.py`, `backend/config.py`, `frontend/src/components/ModelSelector.jsx`

---

## 7. Barge-In State Machine Refinement

**Commit:** `64e4ba5` - *barge in handling improved by adding processing and speaking state*

Added explicit `processing` and `speaking` states to the session state machine so the system knows exactly when barge-in is valid.

### States

```
ready → listening → processing → speaking → ready
                                    ↑
                              barge_in (only valid here)
```

### What changed

- Barge-in events are only accepted when the session is in `speaking` state
- During `processing` state (LLM is generating but TTS hasn't started), barge-in is ignored since there's nothing audible to interrupt
- State transitions are sent to the frontend so the UI accurately reflects what the system is doing

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| Explicit state machine with 4 states | Implicit state from flags (isProcessing, isSpeaking, etc.) | Clear, debuggable transitions. Impossible to be in two states at once. Easy to reason about which actions are valid in each state | More rigid. Edge cases like "LLM is streaming but first TTS chunk hasn't arrived yet" need careful state assignment. Boolean flags would be more flexible for overlapping states |
| Barge-in only during `speaking` | Allow barge-in during `processing` too | Prevents false barge-ins from triggering before the agent has even started responding | If processing takes 3+ seconds, the user can't interrupt to correct their query. They must wait for the agent to start speaking first |

**Files:** `backend/pipeline/orchestrator.py`, `frontend/src/App.jsx`

---

## 8. Subsentence TTS Chunking

**Commit:** `149ffa5` - *latency improved by subsentence chunking instead of sentence chunking*

Changed the TTS text splitting strategy from sentence-level to subsentence-level boundaries to reduce time-to-first-audio.

### How it works

- The orchestrator maintains a text buffer that accumulates LLM token deltas
- As soon as a split point is found (period, comma, semicolon, colon, question mark, exclamation mark), that chunk is pushed to a TTS queue
- A separate async consumer reads from the queue and synthesizes audio in parallel with continued LLM streaming
- The user hears the first clause while the LLM is still generating the rest

### Before vs After

```
Before (sentence chunking):
  LLM: "I can see your account has a balance of ₹45,230. Would you like to check recent transactions?"
  TTS waits for: ─────────────────────────────────────────[full sentence 1]──→ synthesize → play
  
After (subsentence chunking):
  LLM: "I can see your account has a balance of ₹45,230."
  TTS starts at: ─────[first clause, at comma]──→ synthesize → play
  LLM continues: ─────────────────[rest streams in parallel]
```

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| Split at punctuation marks (.,;:?!) | Split at fixed character count (e.g., every 50 chars) | Punctuation marks are natural prosody boundaries. TTS produces natural-sounding speech at clause boundaries | Very short clauses ("Yes," or "No.") produce choppy audio and waste an API call per fragment. The overhead of many small TTS requests may negate the latency savings |
| Split at punctuation marks | Split at word boundaries with a minimum token threshold | Would avoid tiny fragments | Loses the natural prosody advantage. A 10-word chunk ending mid-phrase sounds unnatural when synthesized |
| Async queue between LLM and TTS | Direct synchronous pipe | Queue decouples production and consumption speeds. If TTS is slow on one chunk, the LLM doesn't block | Queue adds memory overhead and complexity. Unbounded queue growth during long responses could cause memory pressure. If the user barge-ins, queued chunks are wasted |
| Split at punctuation marks | Word-level streaming TTS (e.g., ElevenLabs streaming) | Some TTS providers accept token-by-token input and handle chunking internally | Sarvam's TTS API does not support word-level streaming input; it expects complete text segments. Switching providers would require re-evaluating Indian language quality |

**Files:** `backend/pipeline/orchestrator.py`

---

## 9. Transaction & Payment Agents

**Commit:** `0aa1537` - *transaction agent and payment agent added*

Added two new specialist agents bringing the total to 5, along with expanded database schema and 8 new tools.

### Agents added

**TransactionAgent** handles:
- Balance inquiry (`get_balance`)
- Transaction history (`get_transactions`) 
- Transaction status lookup (`get_txn_status`)
- Dispute filing (`raise_dispute`) — requires mandatory reason
- Account listing (`get_customer_accounts`)

**PaymentAgent** handles:
- Pending bills listing (`get_pending_bills`)
- Loan details (`get_loan_details`)
- Bill payments (`make_payment`) — checks sufficient balance before executing

### Database expansion

Added 4 new tables: `transactions` (19 rows), `bills` (11 rows), `loans` (5 rows), `disputes` (1 pre-existing). Seeded with edge cases like insufficient balance scenarios and pre-existing disputes.

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| 5 separate agents | 2 agents (router + one mega-specialist) | Each agent has a focused system prompt with fewer instructions. LLM follows shorter, specific prompts more reliably than long ones with 15+ tool definitions | Handover latency: switching agents costs one extra LLM turn (~500ms-1s). Cross-domain queries ("check my balance and block my card") require two handovers |
| 5 separate agents | 1 agent with all tools | Zero handover latency. Simpler orchestrator code | System prompt would be 3000+ tokens with all tool definitions and behavior instructions. Tool selection accuracy degrades with more tools. Claude Haiku especially struggles when given >10 tools |
| Pre-seeded edge cases in DB | Dynamic test data generation | Deterministic, reproducible test scenarios. Can demo specific failure paths reliably | Hardcoded data doesn't cover all combinations. Adding new test cases requires modifying seed.py and re-creating the database |
| SQLite with pre-seeded data | Mock API responses / in-memory data | Real SQL queries test actual database interactions. Closer to production behavior | Database file must be regenerated when schema changes. No concurrent write support limits load testing |

**Files:** `backend/agents/transaction_agent.py`, `backend/agents/payment_agent.py`, `backend/tools/transaction_tools.py`, `backend/tools/payment_tools.py`, `backend/database/seed.py`

---

## 10. Escalation to Human Agent

**Commit:** `40fe434` - *added escalate_to_human tool*

Added an `escalate_to_human` tool callable by any agent when automated handling isn't sufficient.

### Escalation triggers

1. **Out of scope** — request is beyond all agents' capabilities (e.g., fund transfers, new account opening)
2. **Emotional distress** — customer shows anger, sadness, or frustration. Agent empathizes first, then escalates
3. **Verification failure** — identity verification failed twice
4. **Customer request** — explicit "let me talk to a human"
5. **Complex issue** — unexpected scenario needing manual intervention

### What it does

- Generates a reference number: `ESC-<YYYYMMDD>-<3-digit-random>`
- Accepts a reason and summary for the human agent
- Returns the reference number to the customer

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| Tool-based escalation | Hardcoded escalation rules in orchestrator | Any agent can escalate with context-specific reasoning. The LLM decides when, not a rule engine | LLM might escalate too eagerly (false positives) or not enough (misses distressed customers). No human-in-the-loop validation before escalation |
| Tool-based escalation | Sentiment analysis model (separate from LLM) | A dedicated sentiment model could score emotional state numerically and trigger at thresholds | Extra model inference adds latency. LLM already understands emotional cues from conversation context. A separate model might disagree with the LLM's assessment |
| Reference number only | Actual queue integration (Zendesk, Freshdesk) | Keeps the demo self-contained without external service dependencies | In production, the reference number is meaningless without a queue system. No actual human receives the escalation |
| Empathize-then-escalate for distress | Immediate escalation | Acknowledging the customer's emotions before transferring is better customer experience | Adds one more LLM turn before the human takes over. A very upset customer might not want to hear the bot's empathy |

**Files:** `backend/tools/escalation_tools.py`, `backend/tools/tool_registry.py`

---

## 11. Identity Verification System

**Commits:** `41e70c2`, `40fe434` - *verification improvements*

The router agent verifies customer identity before allowing access to any banking service. Verification requires three data points.

### Verification flow

1. **Name** — flexible matching: "Rahul" matches "Rahul Sharma" (case-insensitive, first-name-only accepted)
2. **Mobile number** — exact 10-digit match
3. **Date of birth OR last transaction amount** — customer chooses which to provide

### Date normalization

The system handles multiple spoken date formats:
- `15 August 1990` -> `15-08-1990`
- `1990-08-15` (ISO) -> `15-08-1990`
- `August 15th, 1990` -> `15-08-1990`
- `DD/MM/YYYY`, `DD-MM-YYYY` -> normalized
- Ordinal suffixes stripped (st, nd, rd, th)
- Two-digit year expansion (00-25 -> 2000s, 26-99 -> 1900s)

### Failure handling

After 2 failed verification attempts, the system automatically escalates to a human agent instead of asking again.

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| Name + Mobile + DOB/Amount (3-factor) | OTP-based verification | Voice-friendly — customer can speak all three without touching their phone. Works for elderly or less tech-savvy users | Less secure than OTP. Someone who knows a person's name, phone number, and birthday could pass verification. OTP is cryptographically secure but requires SMS infra and phone interaction |
| First-name fuzzy matching | Exact full-name match | Spoken names are often partial ("This is Rahul" not "This is Rahul Sharma"). STT may also transcribe names with different spacing/capitalization | Could match the wrong customer if two customers share a first name but have different last names. In the current 8-person demo DB this isn't an issue but would be in production |
| DOB OR last transaction amount | DOB AND last transaction amount | Giving the customer a choice is better UX. If they don't remember one, they can use the other | Weaker security — only one knowledge factor instead of two. Production systems would likely require both |
| 2 attempts then escalate | 3 attempts / lockout / CAPTCHA | Two attempts is generous enough for transcription errors but doesn't allow brute-force guessing | A legitimate customer with a noisy environment might fail STT-based verification due to transcription errors, not wrong information. Two chances may not be enough |
| LLM extracts verification data from speech | Structured form / DTMF input | Natural conversation — customer says "My name is Rahul, number is 9876543210" in any order and the LLM parses it | LLM can misparse numbers from speech (STT "nine eight seven six" -> LLM might extract "9876" or "98 76"). DTMF (phone keypad) input would be 100% accurate for numbers |

**Files:** `backend/tools/verify_tools.py`, `backend/agents/router_agent.py`

---

## 12. Mandatory Reason Collection for Sensitive Actions

**Commit:** `40fe434` - *made changes in verification and card agent*

Card blocking and dispute filing now require the customer to provide a reason before the action executes.

### How it works

**Card blocking** — agent asks: lost, stolen, or suspicious activity?
**Dispute filing** — agent asks: failed transaction, unauthorized charge, duplicate charge, or incorrect amount?

The agent collects the reason, confirms the action + reason with the customer, and only then calls the tool.

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| LLM-driven reason collection (conversational) | Structured dropdown / IVR menu | Natural flow — customer can explain in their own words. LLM categorizes automatically | LLM might accept vague reasons like "just because" or misclassify the category. A structured menu guarantees a valid reason code |
| Confirm before execution | Execute immediately then inform | Prevents accidental blocks. Customer has a chance to correct ("wait, not that card") | Adds one extra conversational turn. In urgent situations (card stolen right now), the extra confirmation feels slow |
| Reason stored in tool call args | Reason as separate database field / audit log | Tool call logs already contain the full args, so the reason is automatically captured | Harder to query reasons across all blocks/disputes. A separate audit table would enable analytics like "what percentage of blocks are due to theft vs loss" |

**Files:** `backend/agents/card_agent.py`, `backend/agents/transaction_agent.py`

---

## 13. Language Detection & Multilingual Pipeline

**Commits:** `286b4b3` - *language detection updated for both router and subagents*, `40fe434`

The system detects the customer's spoken language and uses it throughout the entire response cycle: STT -> language detection -> LLM instruction -> TTS voice.

### How it works

1. STT returns `language_code` alongside the transcript (e.g., `en-IN`, `hi-IN`)
2. Detected language stored in `session_state["language"]`
3. Every agent's system prompt includes a language instruction that reads from session state
4. TTS receives the detected language as `target_language`
5. No manual language selection needed — speak Hindi, get Hindi back

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| STT-based auto-detection per turn | User selects language at session start | Zero-friction multilingual support. Users can code-switch mid-conversation (common in India: mixing Hindi and English) | Short utterances ("yes", "no", "987") don't carry enough signal for reliable language detection. The system might flip language for single-word responses |
| STT-based auto-detection per turn | Detect once, lock for session | Would prevent language flipping on short utterances | Users who naturally code-switch would be forced into one language. A Hindi speaker saying an English banking term would get an English response |
| Language in agent system prompt | Separate translation layer after LLM response | Simpler LLM prompt; translation handled independently | Extra latency from the translation step. Translation can lose banking-specific terminology nuance. The LLM already knows how to respond in the target language if instructed |
| Sarvam STT for language detection | Dedicated language ID model (e.g., fastText langdetect) | Sarvam's STT already returns language as a byproduct — no additional API call needed | Sarvam's detection is tuned for Indian languages. Non-Indian languages might not be detected. A general-purpose langdetect model covers more languages |

**Files:** `backend/pipeline/stt.py`, `backend/pipeline/tts.py`, `backend/pipeline/orchestrator.py`, all agent files

---

## 14. Silent Agent Handover

**Commit:** `58009e4` - *agents saying handover part handled successfully*

Agents hand off to each other silently — the customer never hears "I'm transferring you to the card department."

### How it works

1. Router agent analyzes intent and returns `[HANDOVER: agent_name]` in its response
2. Orchestrator detects the directive, strips it from spoken output, and switches the active agent
3. A synthetic `[Customer transferred]` message is injected so the new agent knows to pick up from context
4. The new agent runs a follow-up turn immediately, continuing the conversation seamlessly
5. Anti-loop guard: if a specialist tries to hand back to router in the same turn, the router is forced to answer directly

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| Silent handover (customer unaware) | Explicit handover ("Let me connect you to our card specialist") | Creates the illusion of a single knowledgeable agent. Better UX than IVR-style "please hold while I transfer you" | Customer can't tell when they're talking to a different agent. If the specialist gives wrong advice, the customer doesn't know who to blame. Debugging is harder since the customer's perceived experience doesn't match the internal flow |
| `[HANDOVER: name]` directive in LLM response | Structured tool call for routing | Simple to implement. The LLM just appends a text marker; no special tool-calling format needed | Brittle string parsing. If the LLM formats the directive slightly differently (e.g., `[Handover: Card Agent]` vs `[HANDOVER: card_agent]`), it breaks. A tool call would have typed parameters and validation |
| Immediate follow-up turn | Wait for customer confirmation before switching | Faster response — customer gets the specialist's answer in the same breath | If the router misidentifies the intent, the wrong specialist picks up. The customer would have to re-explain their request. A confirmation step would catch routing errors |

**Files:** `backend/pipeline/orchestrator.py`, all agent files

---

## 15. RAG Pipeline for General Q&A

**Commit:** `5ee412b` - *rag added and sarvam 105b model added*

Added a FAISS-based retrieval system so the router agent can answer general banking questions without hardcoding knowledge into the system prompt.

### Architecture

```
Customer asks: "What are your working hours?"
        │
        ▼
search_knowledge_base(query)
        │
        ▼
RAGPipeline.search(query)
  ├── Embed query with all-MiniLM-L6-v2 (384-dim)
  ├── FAISS flat L2 index search
  └── Return top-3 matching chunks
        │
        ▼
RouterAgent uses chunks as context to answer
```

### Knowledge base coverage

30 chunks covering: card services, account management, transactions, disputes, bill payments, loans, cheque services, working hours, fees, service limitations, out-of-scope services, escalation paths.

### Build process

```bash
python -m rag.build_vector_db
# Reads knowledge_base.txt -> embeds -> saves FAISS index + chunks to rag/cache/
```

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| FAISS flat index | Pinecone / Weaviate / ChromaDB | Zero infrastructure, loads from local file, sub-millisecond search on small corpus | FAISS flat (brute-force) doesn't scale beyond ~100K vectors. No metadata filtering, no hybrid search. Pinecone/Weaviate offer managed scaling and advanced querying |
| all-MiniLM-L6-v2 embeddings | OpenAI text-embedding-3-small / Cohere embed | Free, runs locally, no API call needed. 384-dim is compact and fast | MiniLM has weaker semantic understanding than larger embedding models. Hindi queries might not embed well since MiniLM is primarily trained on English. A multilingual model like `paraphrase-multilingual-MiniLM-L12-v2` would handle Hindi better |
| Top-3 chunk retrieval | Top-1 / Top-5 / Re-ranking with cross-encoder | 3 chunks balance recall (finding the answer) with precision (not flooding the LLM with irrelevant context) | More chunks = more tokens = higher LLM cost and potential distraction. Fewer chunks might miss the answer. A re-ranker would improve precision but adds latency |
| Paragraph-level chunking | Sentence-level / sliding window / semantic chunking | Paragraphs in the knowledge base are topic-coherent. Each chunk is a self-contained answer | If two related facts span paragraphs, they won't be in the same chunk. Semantic chunking (split by topic change) would handle this better but is more complex to implement |
| Static knowledge base file | CMS / admin panel / database-backed KB | Simple text file, easy to edit, version-controlled with git | No non-developer can update the knowledge base. Every edit requires running `build_vector_db` again. A CMS would allow business users to maintain FAQ content |
| RAG for general questions | Hardcoded responses in system prompt | More flexible and maintainable. Adding new knowledge doesn't require changing agent code or system prompts | Adds embedding model load time at startup (~2-3 seconds). Retrieval can return wrong chunks for ambiguous queries. The LLM might hallucinate beyond what the retrieved chunks say |

**Files:** `backend/rag/build_vector_db.py`, `backend/rag/pipeline.py`, `backend/tools/rag_tools.py`, `backend/knowledge_base.txt`

---

## 16. TTS Bracket Directive Stripping

Part of the subsentence chunking and handover work across multiple commits.

Agent responses contain internal directives like `[HANDOVER: router]` and `[END_SESSION]` that must never be spoken aloud.

### The problem

The subsentence chunker splits at colons, so `[HANDOVER: router]` becomes two fragments: `[HANDOVER:` and `router]`. A simple `\[.*?\]` regex can't catch split fragments.

### The solution

Three regex passes on each TTS chunk:
1. `\[.*?\]` — strips complete bracket directives
2. `\[.*$` — strips fragment starts (e.g., `[HANDOVER:`)
3. `^[^\[]*\]` — strips fragment ends (e.g., `router]`)

If nothing remains after stripping, the chunk is silently skipped (no TTS API call).

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| Regex stripping in TTS consumer | Separate post-processing step between LLM and chunker | Handles both complete and split directives. Works regardless of chunk boundaries | Regex is fragile. If a customer's actual message contains square brackets (e.g., "my reference is [ABC123]"), it would be incorrectly stripped |
| Three-regex approach | Single regex with DOTALL/multiline across buffer | Each regex handles one case simply. Easy to understand and debug | Three regex passes per chunk is technically slower than one pass. But the overhead is negligible compared to TTS API latency |
| Strip in TTS consumer | Prevent directives from entering the text buffer | TTS consumer is the last gate before audio synthesis — safest place to filter | If the LLM generates a directive mid-word (unlikely but possible), the stripping could mangle the word |

**Files:** `backend/pipeline/orchestrator.py`

---

## 17. Persistent WebSocket TTS Connection

Part of the initial architecture, refined across commits.

The TTS WebSocket connection is pre-warmed during the user's speaking turn so the handshake latency overlaps with STT/LLM processing.

### How it works

- When a session starts, the TTS WebSocket is opened and kept alive
- When the LLM produces the first text chunk, TTS synthesis begins immediately without a connection handshake
- If the connection drops, it auto-reconnects with the next chunk (recovery time tracked as `recovery_ms` in metrics)

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| Persistent WebSocket | New HTTP request per TTS chunk | Eliminates ~200-500ms WebSocket handshake per turn. Critical for time-to-first-audio | Idle connections consume server resources. If the user pauses for 2+ minutes, the connection may timeout and need recovery |
| Persistent WebSocket | REST API with HTTP/2 connection reuse | HTTP/2 multiplexing can amortize connection costs similarly | Sarvam's TTS API is WebSocket-native with streaming output. REST would require polling or SSE, adding complexity |
| Pre-warm during user turn | Connect on-demand when LLM produces first chunk | Overlaps handshake with productive work (STT processing), so the user never waits for TTS connection | Wastes a connection if the user disconnects before the agent responds. Connection pool overhead even when the agent has nothing to say |

**Files:** `backend/pipeline/tts.py`, `backend/pipeline/orchestrator.py`

---

## 18. Dual STT Path (Streaming + Batch Fallback)

Part of the initial STT implementation.

The system streams audio to Sarvam's STT in real-time. If streaming fails, it falls back to batch transcription.

### How it works

1. **Primary:** Audio chunks sent over a persistent WebSocket to Sarvam Saaras v3 in real-time. Interim results returned for immediate display.
2. **Fallback:** If the WebSocket drops or returns an error, the system buffers the audio and sends it as a single batch HTTP request after speech ends.

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| Streaming STT with batch fallback | Streaming only | Resilient to intermittent WebSocket failures without losing the user's utterance | Batch fallback adds the full audio duration as latency (user speaks for 3 seconds -> 3 second buffer -> batch -> wait for result). Streaming would have returned partial results during those 3 seconds |
| Streaming STT with batch fallback | Batch only | Would be simpler — no WebSocket management, just send audio blob after speech ends | Adds 1-3 seconds of dead time after the user stops speaking. No interim transcript display. Streaming is strictly better for UX when available |
| Sarvam Saaras v3 | Whisper (local / API) / Google Speech-to-Text / Azure Speech | Sarvam is optimized for Indian accents and languages. Native WebSocket streaming. VAD signals included in the protocol | Sarvam's API availability and uptime are less proven than Google/Azure. Whisper is open-source and free but has higher latency for streaming (requires running a server) |

**Files:** `backend/pipeline/stt.py`

---

## 19. Latency Tracking & Metrics Dashboard

**Commits:** `ef4466f`, `64e4ba5` - logging and latency refinements

Every pipeline stage is timed, metrics are sent to the frontend dashboard per turn, and latency data is persisted to CSV for offline analysis.

### Metrics tracked per turn

| Metric | What it measures |
|--------|-----------------|
| `response_ms` | User stopped speaking -> agent's first audible audio |
| `total_ms` | User stopped speaking -> agent finished speaking |
| `stt_ms` | Speech-to-text processing time |
| `llm_ms` | Full LLM inference (first token to last token) |
| `llm_ttfb_ms` | LLM time-to-first-token |
| `tts_ttfb_ms` | First text chunk sent to TTS -> first audio chunk received |
| `tts_ms` | Total TTS synthesis time |
| `wait_ms` | TTS idle time (waiting for LLM to produce next chunk) |
| `emit_ms` | Time spent sending audio to browser (backpressure) |
| `recovery_ms` | WebSocket reconnection overhead |
| `tool_ms` | Total tool execution time (if any) |

### Frontend LatencyDashboard

Displays metrics from recent turns with a breakdown visualization so developers can identify bottlenecks.

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| Per-turn inline metrics | APM tool (Datadog, New Relic, OpenTelemetry) | No infrastructure needed. Metrics visible in the app itself. Good for debugging during development | No historical views, no alerting, no percentile tracking. Cannot correlate with system metrics (CPU, memory, network) |
| CSV persistence | Time-series database (InfluxDB, Prometheus) | Simple append-only file. Can be analyzed with any tool (Python, Excel, R) | No concurrent write safety. No retention policy. No real-time querying. File grows unbounded |
| Frontend dashboard | Grafana / custom analytics page | Immediate visibility during development and demos. No separate monitoring setup | Frontend dashboard only shows the current session. No cross-session analysis. No comparison between providers or over time |

**Files:** `backend/utils/metrics.py`, `backend/utils/logger.py`, `frontend/src/components/LatencyDashboard.jsx`

---

## 20. Database Design for Edge-Case Testing

**Commit:** `0aa1537` and seed data refinements

The database is seeded with 8 customer personas specifically designed to test edge cases.

### Test personas and their scenarios

| Customer | Scenario | What it tests |
|----------|----------|---------------|
| C001 Rahul Sharma | Happy path: active accounts, cards, loans, bills | Normal flow through all agents |
| C002 Priya Patel | Frozen account, locked netbanking, expired KYC | Account agent error handling |
| C003 Amit Kumar | Active account with pending KYC | Partial service availability |
| C004 Sneha Reddy | ₹350 balance, ₹3,200 electricity bill | Insufficient funds on payment attempt |
| C005 Vikram Singh | Pre-existing open dispute on TXN015 | Duplicate dispute prevention |
| C006 Anjali Desai | 2 accounts, 2 loans, multiple bills | Multi-account disambiguation |
| C007 Mohammed Khan | Everything broken: frozen, locked, PIN blocked, KYC expired | Cascading error messages |
| C008 Deepa Nair | Empty state: no bills, no loans, 1 transaction | Empty result handling |

### Alternatives & Tradeoffs

| Decision | Alternative | Why this was chosen | Tradeoff |
|----------|------------|---------------------|----------|
| Pre-seeded deterministic data | Random test data generation | Every demo produces identical results. Known edge cases are always testable. Reference numbers are predictable | Doesn't cover combinations not explicitly seeded. Real-world data distributions are not represented |
| 8 personas covering key scenarios | 100+ personas with comprehensive coverage | Manageable set for manual testing and demos. Each persona has a clear purpose | Missing edge cases: concurrent sessions for same customer, very long names, special characters in names, non-Indian phone formats |
| Seeded at application start | Migration-based schema management (Alembic) | Simple: drop and recreate. Fine for prototype stage | Cannot evolve schema without data loss. No versioning, no rollback. Production would need proper migrations |

**Files:** `backend/database/seed.py`, `backend/database/connection.py`, `backend/database/queries.py`

---

## 21. Known Issues

These are identified problems that affect the current implementation:

| Issue | Root Cause | Impact | Potential Fix |
|-------|-----------|--------|---------------|
| **Duplicate first audio chunk** | Pre-buffer sends the speech-start frame twice to STT | Repeated digits in transcription (e.g., "897" -> "8997") | Deduplicate frames at the pre-buffer boundary before sending |
| **VAD gets stuck at 'ended'** | Relies on server acknowledgment to resume; if delayed, mic stays dead | User must refresh page to recover | Client-side timeout to auto-resume VAD if server doesn't acknowledge within 3 seconds |
| **1500ms silence timeout splits number dictation** | Users pause mid-number and VAD finalizes the utterance | Phone numbers and amounts get split across turns | Increase timeout during number-expected contexts, or buffer sequential short utterances |
| **ScriptProcessor on main thread** | Using deprecated Web Audio API that runs audio processing on the UI thread | Audio timing jitter during heavy UI rendering | Migrate to AudioWorklet (runs in separate thread with guaranteed timing) |
| **Echo triggers false barge-in** | Agent's voice leaks from speakers into microphone | Agent interrupts itself, cancels its own response | Implement acoustic echo cancellation (AEC), or use WebRTC's built-in echo cancellation constraints |
| **Language flips on short utterances** | "yes" or "987" doesn't carry enough signal for language detection | Response language changes unexpectedly for single-word answers | Lock language after first confident detection; only change on utterances longer than N words |
| **Pre-buffer noise transcribed** | ~1 second of ambient audio before speech is sent to STT | Garbage text at the start of transcription | Apply energy threshold to pre-buffer frames; only send frames above minimum energy |
| **TTS wastes API calls after barge-in** | In-flight TTS synthesis can't be cancelled at the API level | Paid API calls whose results are discarded | Track in-flight requests and skip processing their responses; accept as unavoidable API cost |
| **False barge-in skips agent response** | Noise during agent speech triggers barge-in; STT returns empty transcript | Agent's remaining response is permanently lost, turn ends silently | If barge-in STT returns empty/very short transcript, treat as false positive and resume agent audio playback |

---

## Timeline Summary

| Date | Commit | Change |
|------|--------|--------|
| Jun 19, 2026 | `c702e5a` | Foundation: FastAPI + React + WebSocket + 3 agents + SQLite |
| Jun 19, 2026 | `9f69873` | Client-side VAD with energy-based speech detection |
| Jun 19, 2026 | `ef4466f` | Session logging + latency CSV tracking |
| Jun 20, 2026 | `41e70c2` | Session cleanup + agent context transfer |
| Jun 20, 2026 | `f7dd052` | Server-side barge-in handling |
| Jun 20, 2026 | `6965b36` | Sarvam 30B LLM provider |
| Jun 20, 2026 | `64e4ba5` | Barge-in state machine (processing/speaking states) |
| Jun 20, 2026 | `149ffa5` | Subsentence TTS chunking for lower latency |
| Jun 20, 2026 | `0aa1537` | Transaction + Payment agents, 4 new DB tables |
| Jun 21, 2026 | `40fe434` | Escalation tool, mandatory reasons, verification fixes |
| Jun 21, 2026 | `286b4b3` | Language detection across full pipeline |
| Jun 21, 2026 | `58009e4` | Silent agent handover (no customer-visible transfer) |
| Jun 21, 2026 | `5ee412b` | RAG pipeline + Sarvam 105B model |
