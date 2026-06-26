# Banking Voice Agent — Complete Project Overview

## Goal

Build a **from-scratch, real-time voice pipeline for a banking customer service agent** that handles common banking operations entirely through spoken conversation. The system listens to a customer speaking into a browser microphone, understands their intent, performs banking operations (card blocking, balance checks, bill payments, etc.) via tool calls against a database, and speaks the response back — all streaming in real-time over a single WebSocket connection.

The aim is to demonstrate that an LLM-powered multi-agent system can handle structured, multi-step banking workflows end-to-end through voice, with identity verification, intent routing, multilingual support (Hindi/English/Hinglish), and safe escalation to a human when needed.

**Bank name:** Horizon Bank (fictional)

**Stack:** Python (FastAPI) backend, React (Vite) frontend, SQLite database, Sarvam Saaras v3 (STT), Sarvam Bulbul v3 (TTS), Anthropic Claude / Sarvam LLMs.

---

## Architecture (End-to-End Pipeline)

```
Browser Mic → WebSocket → Sarvam STT (streaming) → Multi-Agent LLM System → Sarvam TTS (streaming) → WebSocket → Browser Speaker
```

### Turn-by-Turn Flow

Each customer utterance goes through this pipeline:

1. **Audio Capture** — Browser captures mic at 16kHz PCM mono, chunked every ~100ms. Client-side VAD (Voice Activity Detection) with 4-frame pre-buffer detects speech onset without clipping.
2. **Speech-to-Text** — Audio chunks stream over WebSocket to Sarvam Saaras v3. Built-in VAD detects speech start/end. Returns transcript with detected language.
3. **Language Detection** — STT returns detected language (Hindi, English, Hinglish). Re-detected on every utterance so the system switches languages mid-conversation if the customer does.
4. **Agent Reasoning** — Transcript is fed to the active agent (Router or specialist). The LLM streams response tokens back in real-time. If the LLM calls tools, they execute against the database, results are fed back, and the LLM continues reasoning (tool-call loop).
5. **Agent Handover** — If the LLM includes `[HANDOVER: agent_name]` in its response, the orchestrator switches the active agent and (if needed) re-runs with the new agent.
6. **Text-to-Speech** — The agent's final response text streams to Sarvam Bulbul v3 over WebSocket, which returns audio chunks progressively.
7. **Audio Playback** — Audio chunks are queued in the browser and played gaplessly at 24kHz.
8. **Barge-in** — If the customer starts speaking while the agent is still talking, STT VAD fires, TTS connection is cancelled, and the new utterance is processed immediately.

### Latency Tracking

Every turn records per-stage latencies:
- STT processing time
- LLM first-token latency
- LLM total processing time
- TTS first-chunk latency
- TTS total time
- Tool call durations
- End-to-end total

These are displayed in real-time on the frontend latency dashboard.

---

## Agent System — Router + 4 Specialist Sub-Agents

The system uses a **hub-and-spoke agent architecture**. The Router Agent is the entry point and coordinator. It verifies identity, classifies intent, and hands over to one of four specialist agents. When a specialist finishes, it hands back to the Router, which asks "anything else?" and can route to a different specialist or end the session.

### How Handovers Work

Agents signal handovers by including `[HANDOVER: agent_name]` in their LLM response text. The `BaseAgent.run()` method parses this with regex. The orchestrator then:
1. Switches the active agent to the target
2. If needed, re-runs the turn with the new agent (the conversation history carries the context)
3. Emits an `agent_handover` event to the frontend so the UI updates the agent label

Specialist agents hand back to router via `[HANDOVER: router]` when done. The router can also end the session via `[END_SESSION]`.

---

### Agent 1: Router Agent (Primary / Hub)

**Role:** First point of contact. Handles greeting, identity verification, intent classification, routing to specialists, "anything else?" follow-ups, and session termination.

**Agent name:** `router`

**Tools available:**
| Tool | Purpose |
|------|---------|
| `verify_identity` | Verifies customer using name + mobile number + DOB or last transaction amount |
| `escalate_to_human` | Escalates to a human agent with reference number (for out-of-scope, emotional distress, or failed verification) |
| `search_knowledge_base` | RAG search over Horizon Bank's FAQ/policy knowledge base for general questions |

**Workflow:**
1. Greets the customer ("Welcome to Horizon Bank")
2. Asks for name, mobile number, and verification answer (DOB or last transaction amount)
3. Calls `verify_identity` — if it fails, allows one retry, then escalates to human
4. Once verified, classifies intent and routes:
   - Card-related → `[HANDOVER: card_agent]`
   - Account access/cheque → `[HANDOVER: account_agent]`
   - Balance/transactions/disputes → `[HANDOVER: transaction_agent]`
   - Bills/EMI/loans → `[HANDOVER: payment_agent]`
   - Out of scope → calls `escalate_to_human` + `[END_SESSION]`
5. After specialist completes, asks "Is there anything else I can help you with?"
6. If no → warm goodbye + `[END_SESSION]`

**Special behaviors:**
- **Emotional distress detection:** Before routing, checks if the customer sounds very angry, distressed, or depressed. If so, empathizes first, then escalates to human with reason `emotional_distress`.
- **Disambiguation rules:** Detailed rules for ambiguous intent (e.g., "account" + balance → transaction_agent, "account" + locked → account_agent, "card" + payment → payment_agent, "card" + lost → card_agent). When in doubt between account_agent and transaction_agent, defaults to transaction_agent.
- **General questions:** If the customer asks a general question ("what can you help me with?"), uses `search_knowledge_base` to answer from the RAG knowledge base before routing.

---

### Agent 2: Card Agent (Specialist)

**Role:** Handles card blocking for lost, stolen, or suspicious activity.

**Agent name:** `card_agent`

**Tools available:**
| Tool | Purpose |
|------|---------|
| `get_card_list` | Fetches all cards (debit/credit) linked to the customer. Returns card_id, card_type, card_network, last_four, status, expiry |
| `block_card` | Permanently blocks a card. Requires card_id and reason (lost/stolen/suspicious_activity). Returns reference number |

**Workflow:**
1. Reads conversation history to understand what the customer already said (does NOT re-ask)
2. Calls `get_card_list` to fetch all cards
3. If multiple active cards → asks which one (by card type + last 4 digits)
4. Asks for reason (lost / stolen / suspicious activity)
5. Confirms before blocking: "I will block your Visa debit card ending in 4521 because it has been reported as lost. Shall I go ahead?"
6. On confirmation → calls `block_card`
7. Reads back reference number, mentions replacement card process (5-7 working days)
8. Hands back: `[HANDOVER: router]`

**Scope boundaries:** Only handles card listing and blocking. Card balance, card statements, card payments → redirects back to router.

---

### Agent 3: Account Agent (Specialist)

**Role:** Handles account access issues (frozen, locked, KYC) and cheque stopping.

**Agent name:** `account_agent`

**Tools available:**
| Tool | Purpose |
|------|---------|
| `get_account_status` | Checks account for access problems: frozen status, locked netbanking, blocked debit card PIN, expired/pending KYC. Returns issues array with severity and resolution |
| `stop_cheque` | Stops a cheque payment. Requires account_id, cheque_number, amount. Returns reference number |

**Workflow for account access:**
1. Calls `get_account_status` with the account_id
2. Focuses ONLY on problems: frozen account, locked netbanking, blocked PIN, KYC issues
3. Explains each issue in plain language: what's wrong, what the customer can't do, how to fix it
4. If no issues → "Your account access is all fine, there are no issues"
5. Does NOT read out balance (that's transaction_agent's job)

**Workflow for stop cheque:**
1. Asks for cheque number
2. Asks for amount (for verification)
3. Confirms: "You want to stop cheque number 123 for rupees 15000, is that correct?"
4. On confirmation → calls `stop_cheque`
5. Reads back reference number

**Scope boundaries:** Only handles access issues and cheque stopping. Account balance, transaction history, failed transactions, bills, card blocking → redirects back to router.

---

### Agent 4: Transaction Agent (Specialist)

**Role:** Handles balance inquiries, transaction history, transaction status checks, and dispute filing.

**Agent name:** `transaction_agent`

**Tools available:**
| Tool | Purpose |
|------|---------|
| `get_customer_accounts` | Fetches all accounts (savings/current) for a customer. Returns account_id, type, balance, status. MUST be called first |
| `get_balance` | Returns current balance for a specific account |
| `get_transactions` | Returns N most recent transactions (default 5). Each has txn_id, amount, type, description, status, date |
| `get_txn_status` | Gets detailed status of one specific transaction + any existing dispute info |
| `raise_dispute` | Raises a formal dispute for a transaction. Requires txn_id and reason. Returns reference number |

**Workflow for balance:**
1. Calls `get_customer_accounts` first (required to get account_id)
2. If multiple accounts → asks which one
3. Calls `get_balance`
4. Reads balance naturally: "Your savings account balance is rupees forty-five thousand two hundred and thirty"

**Workflow for transactions:**
1. Calls `get_customer_accounts` → then `get_transactions`
2. Describes each naturally (description, amount, type) — never reads internal txn_ids

**Workflow for disputes:**
1. Uses `get_transactions` to find the problematic transaction
2. Uses `get_txn_status` to check detailed status
3. Asks customer for dispute reason (failed_transaction / unauthorized_charge / duplicate_charge / incorrect_amount)
4. Confirms before raising
5. Calls `raise_dispute` → reads back reference number

**Scope boundaries:** Only handles balance, transactions, and disputes. Bill payments, loan details, card blocking, account access, cheques → redirects back to router.

---

### Agent 5: Payment Agent (Specialist)

**Role:** Handles bill payments, EMI payments, and loan information.

**Agent name:** `payment_agent`

**Tools available:**
| Tool | Purpose |
|------|---------|
| `get_customer_accounts` | Fetches all accounts. MUST be called first |
| `get_pending_bills` | Returns all unpaid/overdue bills (electricity, water, gas, insurance, EMI). Each has biller_name, biller_id, bill_type, amount, due_date, status |
| `get_loan_details` | Returns active loan details: loan_type, principal, outstanding, EMI amount, interest rate, tenure, next due date |
| `make_payment` | Pays a pending bill. Requires account_id, biller_id, amount. Checks sufficient balance. Deducts from account. Returns reference number + new balance |

**Workflow for bill payment:**
1. Calls `get_customer_accounts` → then `get_pending_bills`
2. Describes pending bills naturally
3. If multiple → asks which to pay
4. Confirms: "I will pay your electricity bill of rupees two thousand to Tata Power. Shall I proceed?"
5. On confirmation → calls `make_payment`
6. Reads back reference number and new account balance
7. If insufficient balance → informs customer, does not attempt payment

**Workflow for loan details:**
1. Calls `get_customer_accounts` → then `get_loan_details`
2. Shares details naturally: "Your home loan has an outstanding balance of rupees eighteen lakhs. Your monthly EMI is rupees eighteen thousand five hundred, due on the 5th of next month."

**Scope boundaries:** Only handles bills, payments, and loans. Balance inquiries, transactions, disputes, card blocking, account access, cheques → redirects back to router.

---

## All 14 Tools — Complete Reference

| # | Tool Name | Used By | Parameters | What It Does |
|---|-----------|---------|------------|--------------|
| 1 | `verify_identity` | Router | name, mobile_number, verification_answer | Looks up customer by mobile, matches name (first name accepted), verifies DOB (any spoken format, auto-normalized) or last transaction amount |
| 2 | `escalate_to_human` | Router | reason, summary | Generates escalation reference number (ESC-YYYYMMDD-XXX). Reasons: out_of_scope, emotional_distress, verification_failed, customer_request, complex_issue |
| 3 | `search_knowledge_base` | Router | query | RAG search over FAISS vector DB (all-MiniLM-L6-v2 embeddings). Returns top 3 chunks from knowledge_base.txt |
| 4 | `get_card_list` | Card | customer_id | Returns all cards: card_id, card_type (debit/credit), card_network (Visa/Mastercard/RuPay), last_four, status (active/blocked/expired), expiry |
| 5 | `block_card` | Card | card_id, reason | Sets card status to blocked. Generates reference (BLK-YYYYMMDD-XXX). Fails if already blocked. Irreversible |
| 6 | `get_account_status` | Account | account_id | Returns account status + issues array (frozen, locked netbanking, blocked PIN, expired KYC) with severity and resolution guidance |
| 7 | `stop_cheque` | Account | account_id, cheque_number, amount | Stops a cheque. Generates reference (STP-YYYYMMDD-XXX). Fails if already cleared or already stopped |
| 8 | `get_customer_accounts` | Transaction, Payment | customer_id | Returns all accounts: account_id, account_type, balance, status. Required first step for account-specific tools |
| 9 | `get_balance` | Transaction | account_id | Returns account balance, type, and status |
| 10 | `get_transactions` | Transaction | account_id, count (default 5) | Returns N recent transactions: txn_id, amount, type (credit/debit), description, status, date |
| 11 | `get_txn_status` | Transaction | txn_id | Returns detailed transaction status + any existing dispute info (dispute_id, status, reference, reason) |
| 12 | `raise_dispute` | Transaction | txn_id, reason | Creates formal dispute. Generates reference (DSP-YYYYMMDD-XXX). Reasons: failed_transaction, unauthorized_charge, duplicate_charge, incorrect_amount. Fails if dispute already exists |
| 13 | `get_pending_bills` | Payment | account_id | Returns unpaid bills: biller_name, biller_id, bill_type (electricity/water/gas/insurance/emi), amount, due_date, status (pending/overdue) |
| 14 | `get_loan_details` | Payment | account_id | Returns active loans: loan_type, principal, outstanding, EMI amount, interest rate, tenure, next due date |
| 15 | `make_payment` | Payment | account_id, biller_id, amount | Pays a bill. Checks amount match + sufficient balance. Deducts from account. Generates reference (PAY-YYYYMMDD-XXX). Returns new balance |

---

## Verification System — Deep Dive

Identity verification is the gate before any banking operation. The system uses a 3-factor check:

1. **Name** — Customer says their name. First name alone is accepted (fuzzy match: "Rahul" matches "Rahul Sharma"). Case-insensitive.
2. **Mobile number** — 10-digit registered number. Exact match against database.
3. **Verification answer** — Either:
   - **Date of birth** — The system normalizes spoken dates aggressively. Handles: "15-08-1990", "August 15 1990", "15th August nineteen ninety", "1990/08/15", etc. Strips prefixes like "my date of birth is" or "I was born on". Handles DD-MM-YYYY, MM-DD-YYYY, YYYY-MM-DD, and month-name formats.
   - **Last transaction amount** — Matches against the most recent completed transaction on any of the customer's accounts. Accepts "2500" or "2500.00".

If verification fails twice, the router escalates to a human agent with reason `verification_failed`.

---

## RAG Knowledge Base

The system includes a FAISS-based vector search over a curated knowledge base for answering general questions.

**Embedding model:** all-MiniLM-L6-v2 (sentence-transformers)
**Index:** Pre-built FAISS index stored in `backend/rag/cache/`

**Knowledge base covers:**
- What services Horizon Bank offers through this helpline (card blocking, balance, transactions, bills, loans, account access, cheques)
- What services are NOT available (fund transfers, new accounts, credit card applications, investments, insurance)
- Card blocking process and replacement timeline
- Dispute process and investigation timeline (7-10 working days)
- Cheque stopping rules
- Escalation to human agent

**When used:** The router agent calls `search_knowledge_base` when a customer asks a general question like "what can you help me with?" or "do you offer fund transfers?" rather than a specific banking operation.

---

## Database Schema — 8 Tables

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `customers` | Identity and verification data | customer_id, name, mobile, dob, language_pref |
| `accounts` | Bank accounts | account_id, customer_id, account_type, balance, status, netbanking_status, debit_card_pin, kyc_status |
| `cards` | Debit and credit cards | card_id, customer_id, card_type, card_network, last_four, status, blocked_reason, block_ref |
| `cheques` | Cheque book records | cheque_id, account_id, cheque_number, amount, payee, status, stop_ref |
| `transactions` | Transaction history | txn_id, account_id, amount, txn_type, description, status |
| `bills` | Pending bills (electricity, water, etc.) | bill_id, account_id, biller_name, biller_id, bill_type, amount, due_date, status |
| `loans` | Active loans | loan_id, account_id, loan_type, principal, outstanding, emi_amount, interest_rate, tenure_months |
| `disputes` | Transaction disputes | dispute_id, txn_id, account_id, reason, status, reference |

**Seeded data:** 3 customers, 4 accounts, 6 cards, 4 cheques, 10 transactions, bills, and loans. Designed to exercise all tool paths:
- Customer C001 has 2 cards (one active, one already blocked) — tests both block success and "already blocked" failure
- Customer C002 has a frozen account — tests get_account_status with issues
- Cheque CHQ002 is already cleared — tests stop_cheque failure case
- A failed transaction exists — tests dispute flow

---

## LLM Provider System

The system supports multiple LLM providers through an abstract interface. Providers are swappable via a frontend dropdown without code changes.

| Provider | Model | How It's Used |
|----------|-------|---------------|
| **Anthropic** | Claude Sonnet 4.6 | Primary provider. Streaming via `anthropic` SDK. Full tool-use support. Best quality for routing and disambiguation |
| **Sarvam 30B** | sarvam-m4-ultra | Alternative provider. Streaming via OpenAI-compatible API. Tool-use support. Better at Hindi-native responses |
| **Sarvam 105B** | sarvam-r1 | Largest Sarvam model. Same API format. Highest Hindi quality but slower |

All providers implement the same `BaseLLMProvider` interface:
- `stream(messages, tools)` → yields `StreamEvent` (text_delta, tool_use, message_end)
- `format_tool_result(tool_use_id, result)` → provider-specific message format
- `format_tool_definitions(tools)` → provider-specific tool schema format

---

## Frontend — Complete UI

### Layout
3-column responsive grid:
- **Left:** Transcript panel (scrollable chat with user/agent bubbles)
- **Center:** Voice button (primary interaction element)
- **Right:** Tool call panel (top) + Latency dashboard (bottom)

### Components

**VoiceButton** — Large circular button with:
- Audio-level ring visualization (dynamic radius based on mic volume)
- VAD status indicator (green dot when speech detected)
- State machine: idle → connecting → ready → listening → processing → speaking
- Visual feedback: mic icon, spinner, pulse animation, waveform

**Transcript** — Scrollable chat:
- User messages right-aligned, agent messages left-aligned
- Agent name labels (Router / Card Services / Account Services / Transaction Services / Payment Services)
- Streaming agent responses with blinking cursor (real-time token display)
- Auto-scroll to bottom

**ToolCallPanel** — Tool execution monitor:
- Shows tool name, arguments, and status (spinner while running, checkmark when done)
- Expandable result inspection (formatted JSON)
- Execution time badge (e.g., "45ms")

**LatencyDashboard** — Stacked horizontal bar chart:
- Color-coded segments: STT (blue), LLM first token (yellow), LLM total (orange), TTS (green), tool calls (purple)
- Legend with precise millisecond values
- Total latency summary

**ModelSelector** — Dropdown: Claude (Anthropic), Sarvam-30B, Sarvam-105B. Disabled during active sessions.

### Hooks

**useWebSocket** — WebSocket lifecycle management:
- Message queuing (queues outbound messages before connection is established)
- Heartbeat ping every 30 seconds
- Auto-reconnect on failure (3-second delay)
- Clean JSON parse with error handling

**useAudioRecorder** — Microphone capture:
- Client-side VAD with configurable RMS threshold
- 4-frame pre-buffer (captures speech onset without clipping)
- State machine: silence → speech → trailing_silence → ended
- PCM16 encoding at 16kHz mono
- Base64 encoding for JSON transport
- Echo cancellation and noise suppression enabled

**AudioPlaybackQueue** — TTS audio playback:
- Queue-based sequential playback (no gaps between chunks)
- 24kHz sample rate (matches Sarvam TTS output)
- Stop control for barge-in (clears queue immediately)

---

## WebSocket Protocol

### Browser → Backend

| Message Type | Payload | When Sent |
|-------------|---------|-----------|
| `start_session` | `{ config: { llm_provider: "anthropic" } }` | User clicks start |
| `audio_chunk` | `{ data: "<base64 PCM>" }` | Every ~100ms while recording |
| `stop_recording` | `{}` | User releases mic button |
| `end_session` | `{}` | User ends conversation |

### Backend → Browser

| Message Type | Payload | Purpose |
|-------------|---------|---------|
| `state` | `{ state: "ready"\|"listening"\|"processing"\|"speaking" }` | Drives VoiceButton visual state |
| `transcript_user` | `{ text: "mera card block karo" }` | STT result → chat bubble |
| `transcript_agent` | `{ text: "I'll", delta: true }` | Streamed LLM token → live typing |
| `transcript_agent` | `{ text: "I'll help you...", delta: false }` | Final complete response |
| `agent_handover` | `{ from: "router", to: "card_agent" }` | Agent switch → label update |
| `tool_call_start` | `{ name: "get_card_list", args: {...} }` | Tool invoked → spinner |
| `tool_call_end` | `{ name: "get_card_list", result: {...}, duration_ms: 45 }` | Tool done → checkmark |
| `audio_chunk` | `{ data: "<base64 audio>", content_type: "audio/wav" }` | TTS audio → playback queue |
| `latency` | `{ metrics: { stt_ms, llm_first_token_ms, tts_ms, total_ms } }` | Latency dashboard update |
| `turn_complete` | `{}` | Reset tool calls, finalize transcript |
| `error` | `{ stage: "stt"\|"llm"\|"tts", message: "..." }` | Error display |

---

## Use Cases — Complete Matrix

| # | Use Case | Handled By | Tools Called (in order) | User Says (example) |
|---|----------|-----------|------------------------|---------------------|
| 1 | Block lost/stolen card | Card Agent | get_card_list → block_card | "My card is lost, I want to block it" |
| 2 | Account access issues | Account Agent | get_account_status | "My netbanking is locked" / "My account is frozen" |
| 3 | Stop a cheque | Account Agent | stop_cheque | "I want to stop cheque number 123" |
| 4 | Check balance | Transaction Agent | get_customer_accounts → get_balance | "What is my account balance?" |
| 5 | View transactions | Transaction Agent | get_customer_accounts → get_transactions | "Show me my recent transactions" |
| 6 | Check failed transaction | Transaction Agent | get_customer_accounts → get_transactions → get_txn_status | "My payment of 999 rupees failed" |
| 7 | Raise dispute | Transaction Agent | get_customer_accounts → get_transactions → get_txn_status → raise_dispute | "I see an unauthorized charge" |
| 8 | Pay a bill | Payment Agent | get_customer_accounts → get_pending_bills → make_payment | "I want to pay my electricity bill" |
| 9 | Check loan/EMI details | Payment Agent | get_customer_accounts → get_loan_details | "What is my loan outstanding?" |
| 10 | General banking question | Router (RAG) | search_knowledge_base | "What services do you offer?" |
| 11 | Emotional distress | Router | escalate_to_human | "I am so frustrated, nothing is working!" |
| 12 | Out-of-scope request | Router | escalate_to_human | "I want to transfer money to someone" |
| 13 | Verification failure | Router | verify_identity → escalate_to_human | (after 2 failed attempts) |

---

## Where the Model Excels (Better Than Human)

### 1. Consistent Identity Verification
The LLM never forgets to verify identity, never skips a step, and never accidentally leaks customer data in hints. Human agents sometimes shortcut verification under time pressure. The system prompt explicitly forbids suggesting or hinting at the answer ("just say 'please tell me your date of birth'").

### 2. Multilingual Code-Switching
Detects language per-utterance via Sarvam STT and responds in-kind (Hindi, English, Hinglish). A human agent typically picks one language and sticks with it — the model adapts fluidly every turn. The language is re-injected into the system prompt on every message.

### 3. Perfect Disambiguation Routing
The routing table with 5 specialist agents and detailed disambiguation rules means the model rarely sends a customer to the wrong department. It reliably distinguishes:
- "card payment" → payment_agent vs. "card blocked" → card_agent
- "account balance" → transaction_agent vs. "account locked" → account_agent
- "payment failed" → transaction_agent vs. "pay my bill" → payment_agent

### 4. Tool Execution Speed & Accuracy
Database lookups happen in <50ms. The model never misreads a card number or reference number back to the customer. It formats them clearly every time.

### 5. Strict Scope Enforcement
Each specialist agent has a hard-coded scope boundary. If a customer asks the card agent about their balance, it doesn't try to help — it redirects back to the router. This prevents agents from going off-script, something human agents sometimes do.

### 6. 24/7 Availability + Infinite Patience
Never frustrated, never tired, handles the same "what's my balance" question at 3am with the same tone as 3pm.

### 7. Structured Escalation
When it can't help, it generates a reference number and warm handoff — every single time. Human agents sometimes drop calls or forget to log escalations. The system has 5 distinct escalation reasons (out_of_scope, emotional_distress, verification_failed, customer_request, complex_issue).

### 8. Date Format Normalization
The verify_identity tool handles spoken dates in any format: "15-08-1990", "August 15th 1990", "15/08/90", "I was born on 15th August 1990". A human agent would need the customer to repeat in a specific format.

### 9. Confirmation Before Destructive Actions
Every destructive tool (block_card, stop_cheque, make_payment, raise_dispute) requires explicit verbal confirmation. The prompt enforces this — "ONLY after the customer explicitly confirms." This is more consistent than human agents who sometimes skip confirmation under time pressure.

### 10. Latency Transparency
The latency dashboard makes performance measurable and debuggable per-stage — something impossible with human agents. You can see exactly where time is spent (STT vs LLM vs TTS).

---

## Where the Model Fails / Limitations

### 1. Barge-In Timing Is Imperfect
The system supports barge-in (user interrupts while agent is speaking), but the pipeline delay means the model may still be generating text for a sentence the user already interrupted. The TTS WebSocket is cancelled, but the LLM may have already committed to a response. True natural turn-taking remains difficult.

### 2. STT Errors Cascade Badly
If Sarvam STT misheards "block" as "unblock", or garbles a mobile number like "9876543210" as "9876543110", the LLM has no way to know. It acts on whatever transcript it receives. A human would catch hesitation, intonation cues, or background noise. **Critical for banking operations where mishearing "4521" as "4125" could block the wrong card.**

### 3. Cannot Handle Ambiguity Without Explicit Clarification
The model asks clarifying questions, but it can't read tone of voice for urgency, detect sarcasm, or understand when a customer is being evasive because they're embarrassed about something. It treats all inputs literally.

### 4. No Real Financial Transactions
The system can block cards and stop cheques (status changes in SQLite), and `make_payment` deducts from the local database balance, but there's no integration with actual core banking systems, payment gateways, or card networks. A real deployment would need CBS integration, 2FA/OTP verification, and regulatory compliance.

### 5. Hallucination Risk on Edge Cases
If the RAG knowledge base doesn't cover a topic, the model might generate plausible-sounding but incorrect banking information. The escalation to human helps mitigate this for out-of-scope requests, but there's always a risk of confident wrong answers for edge cases within scope.

### 6. Emotional Intelligence Is Simulated
The "emotional distress detection" works by keyword/pattern matching in the LLM prompt — it can detect explicit frustration ("I'm so angry") but misses subtle cues like long pauses, sighing, or shaking voice that a human agent would pick up from audio. The system has no access to audio features, only text.

### 7. No Memory Across Sessions
Each WebSocket connection is a fresh session. If a customer calls back about an escalation they filed 10 minutes ago, the system doesn't know. There's no CRM integration, session persistence, or customer interaction history.

### 8. Verification Is Brittle for Spoken Input
The date normalization handles many formats, but spoken dates like "fifteenth August nineteen ninety" depend entirely on STT accuracy — if STT outputs "15 august 1990" it works, but "15 august 19 90" might not. A human would work through format confusion naturally.

### 9. Cannot Detect Fraud/Social Engineering
If someone steals a phone and knows the customer's DOB, the system will happily verify and block (or request to unblock) cards. There's no behavioral biometrics, no voice matching, no fraud signals beyond the simple 3-factor verification check.

### 10. Latency Is Still Noticeable
Even with streaming, the full pipeline (STT → LLM first token → TTS first chunk) adds 800ms-2s of perceptible delay. Human-to-human phone conversation has ~200ms round-trip. Users notice the difference, especially on multi-tool-call turns where the LLM loops.

### 11. Single-Turn Tool Limitation
The agent tool-call loop handles multiple sequential tool calls within one turn (e.g., get_customer_accounts → get_balance), but the loop is invisible to the user during execution. On turns with 3+ tool calls, the user experiences a long silence before the response starts streaming.

---

## Things It Simply Cannot Do

- **Fund transfers** (send money to another person or account)
- **OTP/2FA verification** (can't send or receive OTPs)
- **Voice biometric authentication** (no speaker recognition)
- **Process documents** (can't read uploaded ID photos or cheque images)
- **Open new accounts** or process credit card applications
- **Handle investments** (mutual funds, FDs, RDs)
- **Sell insurance products**
- **Dispute resolution** (can file, but not investigate or resolve)
- **Remember previous calls** (no cross-session memory or CRM)
- **Detect caller from phone number** (no telephony/IVR integration)
- **Handle silence/dropped calls gracefully** (relies on VAD signals)
- **Regulatory compliance** (no call recording, consent management, or audit trail beyond session logs)
- **Handle multiple customers simultaneously on one connection** (1 WebSocket = 1 session)

---

## Directory Structure

```
banking-voice-agent/
├── backend/
│   ├── main.py                      # FastAPI app + WebSocket endpoint
│   ├── config.py                    # Environment variables & settings
│   ├── knowledge_base.txt           # RAG source document (Horizon Bank FAQ)
│   ├── pipeline/
│   │   ├── orchestrator.py          # Central coordinator (turn sequencing, agent routing)
│   │   ├── stt.py                   # Sarvam STT WebSocket client
│   │   └── tts.py                   # Sarvam TTS WebSocket client
│   ├── agents/
│   │   ├── base_agent.py            # Abstract agent with streaming tool-call loop
│   │   ├── router_agent.py          # Hub: greeting, verification, routing, escalation
│   │   ├── card_agent.py            # Specialist: card listing & blocking
│   │   ├── account_agent.py         # Specialist: account access & cheque stopping
│   │   ├── transaction_agent.py     # Specialist: balance, transactions, disputes
│   │   └── payment_agent.py         # Specialist: bills, EMIs, loans
│   ├── llm/
│   │   ├── base_provider.py         # Abstract LLM interface (stream, format_tool_*)
│   │   ├── anthropic_provider.py    # Claude streaming + tool-use
│   │   ├── sarvam_provider.py       # Sarvam LLM streaming + tool-use
│   │   └── provider_factory.py      # Factory: "anthropic" / "sarvam" / "sarvam-105b"
│   ├── tools/
│   │   ├── tool_registry.py         # Central registry (14 tools, schemas + handlers)
│   │   ├── verify_tools.py          # verify_identity (date normalization, name matching)
│   │   ├── card_tools.py            # get_card_list, block_card
│   │   ├── account_tools.py         # get_account_status, stop_cheque
│   │   ├── transaction_tools.py     # get_balance, get_customer_accounts, get_transactions, get_txn_status, raise_dispute
│   │   ├── payment_tools.py         # get_pending_bills, get_loan_details, make_payment
│   │   ├── escalation_tools.py      # escalate_to_human
│   │   └── rag_tools.py             # search_knowledge_base
│   ├── rag/
│   │   ├── pipeline.py              # FAISS search + sentence-transformers encoding
│   │   ├── build_vector_db.py       # Script to build FAISS index from knowledge_base.txt
│   │   └── cache/                   # Pre-built faiss.index + chunks.json
│   ├── database/
│   │   ├── connection.py            # Async SQLite (aiosqlite, WAL mode, foreign keys)
│   │   ├── schema.sql               # 8 tables (customers, accounts, cards, cheques, transactions, bills, loans, disputes)
│   │   ├── seed.py                  # Mock data for 3 customers
│   │   └── queries.py               # 24+ typed async query functions
│   └── utils/
│       ├── metrics.py               # Per-turn latency tracking (7 metrics)
│       └── logger.py                # Structured JSON session logging
├── frontend/
│   ├── src/
│   │   ├── App.jsx                  # Root component, state management, WS message routing
│   │   ├── main.jsx                 # React entry point
│   │   ├── components/
│   │   │   ├── VoiceButton.jsx      # Audio-level ring, VAD indicator, state machine
│   │   │   ├── Transcript.jsx       # Streaming chat UI with agent labels
│   │   │   ├── ToolCallPanel.jsx    # Tool execution monitor
│   │   │   ├── LatencyDashboard.jsx # Stacked bar chart (STT/LLM/TTS)
│   │   │   └── ModelSelector.jsx    # LLM provider dropdown
│   │   ├── hooks/
│   │   │   ├── useWebSocket.js      # WS lifecycle, heartbeat, auto-reconnect
│   │   │   └── useAudioRecorder.js  # VAD, pre-buffer, PCM16 encoding
│   │   └── utils/
│   │       └── audio.js             # float32→PCM16 conversion, AudioPlaybackQueue
│   ├── index.html                   # Entry HTML (dark theme, Slate palette)
│   ├── vite.config.js               # React plugin, WS proxy to localhost:8000
│   └── package.json                 # React 19.1, Vite 6.3
└── architecture.md                  # Original technical specification
```

---

## Key Design Decisions

1. **WebSocket-only transport** — No HTTP polling. Everything (audio, transcripts, tool calls, latency, state changes) flows over a single bidirectional WebSocket.
2. **Client-side VAD with pre-buffering** — 4-frame buffer ensures the first syllable of speech is never clipped, even though VAD detection has inherent latency.
3. **Handover via text markers** — `[HANDOVER: agent_name]` parsed from LLM output via regex. Simple, no extra tool needed, and the LLM naturally decides when to hand over as part of its response generation.
4. **Provider abstraction** — Swap LLMs by changing a dropdown (Anthropic / Sarvam 30B / Sarvam 105B). All share the same `BaseLLMProvider` interface.
5. **RAG for FAQ** — Avoids hallucination on policy/service questions by grounding in a curated knowledge base. Only the router uses it.
6. **Emotional escalation in-prompt** — Built into the router's system prompt, not a separate classifier or model. Checks for strong emotional distress before routing.
7. **Scope boundaries per agent** — Each specialist agent has an explicit "NOT YOUR SCOPE" section in its prompt listing what to redirect back to router. Prevents agents from going off-script.
8. **Confirmation before destructive actions** — Every tool that changes state (block_card, stop_cheque, make_payment, raise_dispute) requires the LLM to ask for explicit confirmation first. Enforced in both the tool descriptions and agent prompts.
9. **Never expose internal IDs** — All agent prompts forbid revealing internal IDs (card_id, customer_id, account_id, txn_id, biller_id) to the customer. They reference cards by "Visa ending in 4521", not "CARD001".

---

## Summary

The project is a **fully functional POC** that demonstrates the end-to-end voice AI pipeline for banking. It went significantly beyond the original 3-agent/4-use-case spec to implement **5 agents, 14 tools, RAG, multi-provider LLM support, and emotional escalation**. The frontend is production-quality with real-time streaming UI.

**The model is better than a human at:** consistency, speed, multilingual switching, routing accuracy, scope enforcement, date normalization, confirmation discipline, and 24/7 availability.

**The model is worse than a human at:** reading emotional subtlety from voice, recovering from STT mishearing, handling edge-case ambiguity, detecting fraud/social engineering, building rapport in sensitive conversations, and adapting to completely novel situations.

**What would make this production-ready:** Core banking system integration, OTP/2FA, voice biometrics, call recording/compliance, telephony integration (SIP/IVR), cross-session memory, load testing, and regulatory approval.
