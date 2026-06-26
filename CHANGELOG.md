# Banking Voice Agent — Complete Changelog

All changes made to the banking voice agent, ordered chronologically from the initial commit to the latest state. Each section maps to one or more git commits and describes what was built, why, and which files were involved.

---

## 1. Initial Project Setup

**Commit:** `c702e5a` — *first commit* (Jun 19, 2026)

Built the complete foundation for a real-time voice banking assistant from scratch.

### Tech Stack
- **Backend:** Python, FastAPI, WebSocket server
- **Frontend:** React (Vite), Web Audio API
- **Database:** SQLite with pre-seeded customer/account/card/transaction data
- **STT:** Sarvam Saaras v3 (WebSocket streaming)
- **TTS:** Sarvam Bulbul v3 (WebSocket streaming)
- **LLM:** Anthropic Claude (streaming tool-calling)

### What Was Built

**Voice Pipeline:**
Browser mic → WebSocket → Sarvam STT → Agent System (LLM + tool calls) → Sarvam TTS → WebSocket → Browser speaker. The entire pipeline streams end-to-end over WebSocket connections — no REST polling.

**3-Agent System:**
- **Router Agent** — entry point, handles identity verification and routes to specialist agents
- **Card Agent** — card listing and card blocking
- **Account Agent** — account status inquiry, stop cheque requests

**Tool-Calling Architecture:**
Agents use structured tool calls (not free-text parsing) to interact with the database. Tools are registered in a central registry and dynamically attached to agents based on their role.

**Database Schema:**
SQLite with tables for customers, accounts, cards, cheques, and transactions. Seeded with realistic mock data for testing.

**Frontend:**
React app with components for voice recording (VoiceButton), live transcript display, tool call visualization panel, latency dashboard, and model selector dropdown. Audio is captured as raw PCM and sent over WebSocket.

### Files Created
```
backend/main.py                          — WebSocket server, session management
backend/config.py                        — Environment-based configuration
backend/pipeline/orchestrator.py         — Turn orchestration (STT → LLM → TTS)
backend/pipeline/stt.py                  — Sarvam STT WebSocket client
backend/pipeline/tts.py                  — Sarvam TTS WebSocket client
backend/agents/base_agent.py             — Abstract base agent with streaming LLM
backend/agents/router_agent.py           — Router agent with verification flow
backend/agents/card_agent.py             — Card operations agent
backend/agents/account_agent.py          — Account operations agent
backend/llm/base_provider.py             — LLM provider interface
backend/llm/anthropic_provider.py        — Anthropic Claude implementation
backend/llm/provider_factory.py          — Provider instantiation factory
backend/tools/tool_registry.py           — Central tool registration
backend/tools/verify_tools.py            — Identity verification tools
backend/tools/card_tools.py              — Card-related tools
backend/tools/account_tools.py           — Account-related tools
backend/database/connection.py           — SQLite connection manager
backend/database/schema.sql              — Database schema
backend/database/seed.py                 — Mock data seeding
backend/database/queries.py              — Database query functions
backend/utils/logger.py                  — Logging utilities
backend/utils/metrics.py                 — Latency tracking
frontend/src/App.jsx                     — Main app with WebSocket integration
frontend/src/components/VoiceButton.jsx  — Mic button with recording states
frontend/src/components/Transcript.jsx   — Live conversation display
frontend/src/components/ToolCallPanel.jsx— Tool call visualization
frontend/src/components/LatencyDashboard.jsx — Pipeline latency metrics
frontend/src/components/ModelSelector.jsx— LLM model dropdown
frontend/src/hooks/useWebSocket.js       — WebSocket connection hook
frontend/src/hooks/useAudioRecorder.js   — Raw audio capture hook
frontend/src/utils/audio.js             — PCM encoding and playback utilities
ARCHITECTURE.md                          — Technical specification document
```

---

## 2. Voice Activity Detection (Client-Side VAD)

**Commit:** `9f69873` — *vad added. now able to detect voice on it's own*

Replaced manual stop-recording with automatic speech detection. The system continuously monitors microphone input using the Web Audio API and detects when the user starts and stops speaking — no button press needed.

### How It Works
- Uses **RMS energy levels** with separate thresholds for speech start (`0.025`) and silence detection (`0.015`) to prevent rapid toggling (hysteresis)
- Maintains a **rolling pre-buffer of 4 audio chunks** (~1 second) so the beginning of speech is never clipped
- Tracks three states: `silence` → `speech` → `trailing_silence` → `ended`, with a **1500ms silence window** before finalizing
- **Minimum speech duration of 250ms** filters out short noise bursts and accidental sounds
- VAD can be **paused** (during processing) and **resumed** (when ready for next input) without dropping the audio stream

### Files Modified
```
frontend/src/hooks/useAudioRecorder.js   — VAD algorithm with RMS detection
frontend/src/components/VoiceButton.jsx  — Visual states for VAD feedback
frontend/src/App.jsx                     — VAD callback integration
```

---

## 3. Structured Logging and Per-Session Log Files

**Commit:** `ef4466f` — *server based and session based logging added*

Added structured conversation logging so every session gets its own log file with per-turn data.

### What Gets Logged
- Turn number, user transcript, active agent name
- Agent response text and all tool calls made
- Handover events between agents
- Latency metrics per pipeline stage

### Latency Tracking
The `LatencyTracker` records timestamps at each pipeline stage — STT start/end, LLM start/first-token/end, TTS start/first-chunk/end, individual tool call durations — and computes metrics sent to the frontend's latency dashboard.

### Files Modified
```
backend/utils/logger.py                  — ConversationLogger with per-session files
backend/utils/metrics.py                 — LatencyTracker with stage timestamps
backend/main.py                          — Logger instantiation per session
backend/pipeline/orchestrator.py         — Logger integration into turn processing
```

---

## 4. Session End Handling and Agent Context Transfer

**Commit:** `41e70c2` — *end session resolved, agent context transfer handled*

Fixed two problems: conversations not properly terminating, and agents losing context when customers were handed off between them.

### Context Transfer
All agents share a single `conversation_history` list. When the router hands off to a specialist agent, the new agent sees the entire prior conversation — no explicit state copying needed. The handover is a directive in the LLM response (`[HANDOVER: agent_name]`), and the orchestrator detects it, switches the active agent, and runs a follow-up turn with a synthetic `[Customer transferred]` message.

### Session End
The `[END_SESSION]` directive from the LLM is now properly detected and triggers cleanup — closing the WebSocket, resetting agent state, and logging the session summary.

### Files Modified
```
backend/agents/router_agent.py           — End-session detection
backend/agents/card_agent.py             — Context passing on handover
backend/agents/account_agent.py          — Context receiving from router
backend/pipeline/orchestrator.py         — Session cleanup and handover logic
backend/tools/verify_tools.py            — Session state integration
frontend/src/App.jsx                     — End-session message handling
```

---

## 5. Barge-In Handling (Server-Side)

**Commit:** `f7dd052` — *barge in handling added from server side*

Users can now interrupt the agent mid-speech. When the VAD detects speech while the agent is talking, the system immediately stops audio playback, cancels the ongoing pipeline, and starts listening to the user.

### How It Works
- **Client-side:** Stops the audio playback queue and sends a `barge_in` event over WebSocket
- **Server-side:** Cancels the running `asyncio.Task` for the current turn, including any in-flight LLM streaming and TTS synthesis
- **History preservation:** Partial agent responses are saved to conversation history with an `[interrupted by customer]` marker so the agent has context about what it already said. If the agent hadn't started responding yet, history records `[interrupted before responding]`

### Files Modified
```
backend/config.py                        — Barge-in configuration flags
backend/main.py                          — WebSocket handler for barge_in events
backend/pipeline/orchestrator.py         — asyncio.Task cancellation logic
frontend/src/App.jsx                     — Barge-in event emission
```

---

## 6. Sarvam 30B LLM Provider

**Commit:** `6965b36` — *sarvam 30b params model added*

Added Sarvam AI's 30B parameter model as an alternative LLM provider, better suited for Indian language responses.

### Provider Abstraction
All providers implement the same `BaseLLMProvider` interface, so agents work identically regardless of which LLM is behind them. The provider factory instantiates the correct provider based on the model selected in the frontend dropdown.

### Files Created/Modified
```
backend/llm/sarvam_provider.py           — New Sarvam LLM provider (created)
backend/llm/provider_factory.py          — "sarvam-30b" option added
backend/config.py                        — SARVAM_API_KEY and model config
frontend/src/components/ModelSelector.jsx— Dropdown option added
```

---

## 7. Barge-In State Refinement

**Commit:** `64e4ba5` — *barge in handling improved by adding processing and speaking state*

Refined barge-in detection with explicit pipeline states so interrupts only trigger during actual speech playback, not during LLM processing.

### State Machine
- **`idle`** — waiting for user input
- **`processing`** — LLM is generating (barge-in ignored here)
- **`speaking`** — TTS audio is playing (barge-in active)

This prevents false interrupts where user speech during LLM thinking would kill the turn before the agent even started responding.

### Files Modified
```
backend/pipeline/orchestrator.py         — State tracking and barge-in gating
```

---

## 8. Subsentence TTS Chunking for Lower Latency

**Commit:** `149ffa5` — *latency improved by subsentence chunking instead of sentence chunking*

Previously, the system waited for complete sentences before sending text to TTS. Now it splits the LLM's streaming output at subsentence boundaries for faster time-to-first-audio.

### How It Works
The orchestrator maintains a text buffer that accumulates LLM deltas. As soon as a split point is found (period, comma, semicolon, colon, question mark, exclamation mark), that chunk is pushed to an async TTS queue. A separate async consumer reads from the queue and synthesizes audio in parallel with continued LLM streaming.

The user starts hearing the response while the LLM is still generating the rest of it.

### Bracket Directive Stripping
Agent responses contain internal directives like `[HANDOVER: router]` and `[END_SESSION]` that should never be spoken aloud. Because the subsentence chunker splits on colons, `[HANDOVER: router]` becomes fragments. Three regexes handle all cases:
- `\[.*?\]` — strips complete bracket directives
- `\[.*$` — strips fragment starts like `[HANDOVER:`
- `^[^\[]*\]` — strips fragment ends like `router]`

If nothing remains after stripping, the chunk is silently skipped.

### Files Modified
```
backend/pipeline/orchestrator.py         — Subsentence buffer, TTS queue, regex stripping
```

---

## 9. Transaction Agent and Payment Agent

**Commit:** `0aa1537` — *transaction agent and payment agent added*

Expanded from 3 agents to 5, adding support for transaction history, dispute filing, bill payments, and loan details.

### New Agents

**Transaction Agent:**
- Balance inquiry
- Transaction history retrieval (filterable by date range)
- Dispute filing with mandatory reason collection (failed transaction, unauthorized charge, duplicate charge, incorrect amount)

**Payment Agent:**
- Pending bill listing
- Loan/EMI details
- Bill payment execution

### Database Expansion
New tables and seed data for bills, payments, and loan information.

### Files Created
```
backend/agents/transaction_agent.py      — Transaction history and dispute agent
backend/agents/payment_agent.py          — Bill payment and loan agent
backend/tools/transaction_tools.py       — Transaction query and dispute tools
backend/tools/payment_tools.py           — Bill, payment, and loan tools
```

### Files Modified
```
backend/agents/router_agent.py           — Routing to new agents
backend/database/schema.sql              — New tables for bills and loans
backend/database/queries.py              — Query functions for new tables
backend/database/seed.py                 — Mock data for bills and loans
backend/tools/tool_registry.py           — Registered new tools
backend/pipeline/orchestrator.py         — Support for new agent types
```

---

## 10. Enhanced Verification, Card Agent Improvements, and Human Escalation

**Commit:** `40fe434` — *made changes in verification and card agent, added escalate_to_human tool*

### Identity Verification System
The router agent verifies the customer's identity before allowing access to any banking service. Verification requires three pieces of information:

1. **Name** — matched using flexible matching (case-insensitive, first-name-only accepted). "Rahul" matches "Rahul Sharma"
2. **Mobile number** — exact match lookup in the customer database
3. **Date of birth OR last transaction amount** — either one suffices. Date parsing supports multiple formats (`DD/MM/YYYY`, `DD-MM-YYYY`, `YYYY-MM-DD`, natural language like "15th March 1990")

On successful verification, the customer's full name is used to greet them. On **two failed attempts**, the system escalates to a human agent instead of asking again.

### Mandatory Reason Collection for Sensitive Actions
- **Card blocking** — agent asks whether the card is lost, stolen, or if suspicious activity was noticed
- **Dispute filing** — agent asks whether it's a failed transaction, unauthorized charge, duplicate charge, or incorrect amount

The agent asks for the reason, confirms the action along with the reason, and only then proceeds.

### Escalation to Human Agent
Added an `escalate_to_human` tool that any agent can call. Generates a reference number and accepts a reason and summary.

**Escalation triggers:**
- Customer request is out of scope for all agents
- Customer shows emotional distress (anger, sadness, frustration) — agent empathizes first, then escalates
- Repeated verification failures
- Customer explicitly asks for a human
- Complex issues that need manual intervention

### Files Created
```
backend/tools/escalation_tools.py        — escalate_to_human tool
```

### Files Modified
```
backend/agents/router_agent.py           — Verification flow with failure tracking
backend/agents/card_agent.py             — Mandatory reason for card blocking
backend/agents/transaction_agent.py      — Mandatory reason for disputes
backend/tools/verify_tools.py            — Flexible name matching, date parsing
backend/tools/tool_registry.py           — Registered escalation tool
```

---

## 11. Language Detection Across All Agents

**Commit:** `286b4b3` — *language detection updated for both router and subagents*

The system now detects the customer's spoken language and uses it throughout the entire response cycle.

### Pipeline
1. **STT** returns a `language_code` alongside the transcript (e.g., `en-IN`, `hi-IN`)
2. The detected language is stored in `session_state["language"]`
3. Every agent prompt includes a **language instruction section** that reads from session state, telling the LLM to respond in the same language
4. **TTS** receives the detected language as `target_language` so the spoken response matches

A customer speaking Hindi gets a Hindi response without any manual language selection.

### Files Modified
```
backend/pipeline/stt.py                  — Language code extraction
backend/pipeline/tts.py                  — Target language parameter
backend/pipeline/orchestrator.py         — Language state tracking
backend/agents/router_agent.py           — Language-aware system prompt
backend/agents/card_agent.py             — Language-aware system prompt
backend/agents/account_agent.py          — Language-aware system prompt
backend/agents/transaction_agent.py      — Language-aware system prompt
backend/agents/payment_agent.py          — Language-aware system prompt
```

---

## 12. Agent Handover Acknowledgment

**Commit:** `58009e4` — *agents saying handover part handled successfully*

Refined the handover flow so agent transitions are smooth and visible.

### What Changed
- Agents now explicitly acknowledge successful handover in conversation
- The orchestrator emits handover events to the frontend for display
- Better logging of agent transitions with source and target agent names

### Files Modified
```
backend/pipeline/orchestrator.py         — Handover event emission and logging
backend/agents/router_agent.py           — Handover acknowledgment prompting
```

---

## 13. RAG Pipeline and Sarvam 105B Model

**Commit:** `5ee412b` — *rag added and sarvam 105b model added*

### RAG Pipeline for General Q&A
Added a FAISS-based retrieval system so the router agent can answer general banking questions (hours, fees, limits, supported services) without hardcoding them into the prompt.

**Build phase (run once):**
- `build_vector_db.py` reads `knowledge_base.txt`, splits it into paragraph-level chunks
- Embeds each chunk using `sentence-transformers/all-MiniLM-L6-v2`
- Saves the FAISS index and chunk text to `rag/cache/`

**Runtime phase:**
- `RAGPipeline` loads the cached index and model at startup
- `search_knowledge_base` tool takes a query, embeds it, and returns the top-3 matching chunks
- Router agent uses the retrieved context to answer the customer's question

The knowledge base covers all agent capabilities, service limitations, working hours, fees, and out-of-scope services with fallback to escalation.

### Sarvam 105B Model
Added Sarvam AI's larger 105B parameter model as a third LLM option — stronger reasoning with Indian language support.

### Files Created
```
backend/rag/__init__.py                  — RAG module
backend/rag/pipeline.py                  — FAISS retrieval logic
backend/rag/build_vector_db.py           — Vector index builder
backend/rag/cache/faiss.index            — Pre-built FAISS index
backend/rag/cache/chunks.json            — Pre-computed document chunks
backend/knowledge_base.txt               — Banking FAQ knowledge base
backend/tools/rag_tools.py               — search_knowledge_base tool
```

### Files Modified
```
backend/config.py                        — Sarvam 105B model config
backend/llm/provider_factory.py          — 105B variant support
backend/agents/router_agent.py           — RAG context in system prompt
backend/pipeline/orchestrator.py         — RAG retrieval before LLM calls
backend/tools/tool_registry.py           — Registered RAG tool
```

---

## Current Architecture Summary

### Agent System (5 agents)
| Agent | Role | Tools |
|-------|------|-------|
| Router | Verification, language detection, general Q&A (RAG), routing | verify_identity, search_knowledge_base, escalate_to_human |
| Card | Card listing, card blocking (with reason) | get_cards, block_card, escalate_to_human |
| Account | Account status, stop cheque | get_account_status, stop_cheque, escalate_to_human |
| Transaction | Balance, history, dispute filing (with reason) | get_balance, get_transactions, file_dispute, escalate_to_human |
| Payment | Pending bills, loan details, bill payment | get_pending_bills, get_loan_details, pay_bill, escalate_to_human |

### LLM Providers
| Provider | Model | Best For |
|----------|-------|----------|
| Anthropic | Claude Haiku 4.5 | Tool calling, instruction following (default) |
| Sarvam | 30B | Indian language responses |
| Sarvam | 105B | Stronger reasoning + Indian language support |

### Voice Pipeline
```
Browser Mic
  → Client-Side VAD (RMS energy, pre-buffer, 1500ms silence)
  → WebSocket
  → Sarvam STT (language detection)
  → Agent System (streaming LLM + tool calls)
  → Subsentence Chunking (split at punctuation)
  → Bracket Directive Stripping
  → Sarvam TTS (target language from STT)
  → WebSocket
  → Browser Speaker (with barge-in support)
```

### Directory Structure (Current)
```
va/
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── pipeline/
│   │   ├── orchestrator.py
│   │   ├── stt.py
│   │   └── tts.py
│   ├── agents/
│   │   ├── base_agent.py
│   │   ├── router_agent.py
│   │   ├── card_agent.py
│   │   ├── account_agent.py
│   │   ├── transaction_agent.py
│   │   └── payment_agent.py
│   ├── llm/
│   │   ├── base_provider.py
│   │   ├── anthropic_provider.py
│   │   ├── sarvam_provider.py
│   │   └── provider_factory.py
│   ├── tools/
│   │   ├── tool_registry.py
│   │   ├── verify_tools.py
│   │   ├── card_tools.py
│   │   ├── account_tools.py
│   │   ├── transaction_tools.py
│   │   ├── payment_tools.py
│   │   ├── escalation_tools.py
│   │   └── rag_tools.py
│   ├── database/
│   │   ├── connection.py
│   │   ├── schema.sql
│   │   ├── seed.py
│   │   └── queries.py
│   ├── rag/
│   │   ├── build_vector_db.py
│   │   ├── pipeline.py
│   │   └── cache/
│   ├── utils/
│   │   ├── logger.py
│   │   └── metrics.py
│   └── knowledge_base.txt
├── frontend/
│   └── src/
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
└── ARCHITECTURE.md
```

---

## Known Issues

| # | Issue | Cause | Impact |
|---|-------|-------|--------|
| 1 | Duplicate first audio chunk | Pre-buffer sends the speech-start frame twice to STT | Repeated digits (e.g., "897" → "8997") |
| 2 | VAD gets stuck at 'ended' | Relies on server acknowledgment to resume; if delayed, mic stays dead | User must refresh to recover |
| 3 | 1500ms silence timeout splits number dictation | Users pausing mid-number get cut off | Partial number transcription |
| 4 | ScriptProcessor on main thread | Deprecated API causes audio timing jitter during heavy UI rendering | Inconsistent audio timing |
| 5 | Echo triggers false barge-in | Agent's own voice leaks into mic on speakers (no headphones) | Agent interrupts itself |
| 6 | Language flips on short utterances | "yes" or "987" doesn't have enough signal for reliable language detection | Wrong language response |
| 7 | Pre-buffer noise transcribed | ~1s of ambient audio before speech gets sent to STT | Garbage prefix in transcript |
| 8 | TTS wastes API calls after barge-in | In-flight TTS synthesis can't be cancelled, results thrown away | Unnecessary API cost |
| 9 | False barge-in skips agent response | Noise during agent speech kills playback and cancels the turn; STT returns empty | Agent's remaining response permanently lost |
