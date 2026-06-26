# Horizon Bank Voice Agent — Manual Test Script

A human-driven test plan for the voice agent. Each scenario lists **who you are**
(a seeded customer), **what to say** (in order), and **what should happen**. Speak
the lines into the mic (or type them if you test by text — see the appendix).

> The database was reset to fresh seed data before this script was written. To reset
> again at any time, run from the `backend/` folder: `python reset_db.py`

---

## How to run a test

1. Start the backend (`cd backend && python main.py`) and the frontend (`cd frontend && npm run dev`).
2. Open the app, pick a model in the top-right selector, and click the mic button to start a call.
3. **Every call starts unverified** — the agent verifies you first, every time. Begin each
   scenario with the verification step below using the persona's details.
4. Watch the right-hand **Tool Calls** panel and the **Agent** panel to confirm the
   correct specialist was reached and the correct tool fired. That's how you verify a pass.

### Step 0 — Verify (do this at the start of every call)

The agent asks for one thing at a time. Answer as it asks:

- When greeted / asked how it can help → say what you want (e.g. *"I need to block my card"*).
- When asked your **name** → say the persona's name.
- When asked your **mobile number** → say the 10-digit number.
- When asked your **date of birth** → say it naturally (e.g. *"15 August 1990"*).

> Tip: you can also verify with *"the amount of my last transaction"* instead of DOB,
> but **date of birth is the reliable answer** — use it unless you're specifically
> testing the transaction-amount path.

---

## Personas (verification details)

| ID | Name (say this) | Mobile | Date of birth (say this) | Good for testing |
|----|-----------------|--------|--------------------------|------------------|
| C001 | Rahul Sharma | 9876543210 | 15 August 1990 | Rich data: 2 accounts, cards, home loan, bills, a failed txn |
| C002 | Priya Patel | 9123456789 | 22 March 1985 | Frozen savings + expired KYC + locked netbanking |
| C003 | Amit Verma | 9988776655 | 10 December 1995 | KYC pending (warning) |
| C004 | Sneha Reddy | 9870011223 | 5 May 1992 | Low balance ₹350; one already-blocked credit card |
| C005 | Vikram Singh | 9865432109 | 28 November 1988 | A cleared cheque; a txn that already has a dispute |
| C006 | Anjali Nair | 9854321098 | 12 July 1991 | 2 accounts, 2 loans, multiple bills (one overdue) |
| C007 | Mohammed Khan | 9843210987 | 19 February 1983 | Everything wrong: frozen + netbanking locked + PIN blocked + KYC expired |
| C008 | Deepa Iyer | 9832109876 | 30 September 1996 | Clean account, **no bills, no loans** (empty state) |

**Reference-number prefixes** you should hear on success:
`BLK-` block card · `STP-` stop cheque · `DSP-` raise dispute · `PAY-` bill payment · `ESC-` escalation.

---

## A. Identity & verification (Router agent)

### A1 — Successful verification ✅
**Persona:** Rahul Sharma (C001)
1. "Hello, I need some help with my account."
2. (name) "Rahul Sharma"
3. (mobile) "9876543210"
4. (DOB) "15th August 1990"

**Expect:** `verify_identity` is called and succeeds. Agent greets you by name
("Welcome, Rahul…") and asks how it can help. Session state shows **verified**.

### A2 — Wrong details, retry, then escalate ❌→🧑
**Persona:** Rahul Sharma (C001), but give a **wrong** date of birth.
1. "I want to check my balance."
2. (name) "Rahul Sharma"
3. (mobile) "9876543210"
4. (DOB) "1st January 2000"  ← wrong
5. When it fails, it offers one more try → give a wrong DOB again: "2nd February 2001".

**Expect:** First `verify_identity` fails (politely). After the second failure, the
agent calls `escalate_to_human` with reason **verification_failed**, says a human will
help shortly, and **ends the session**.

---

## B. Card scenarios (Card agent)

### B1 — Block a lost debit card ✅
**Persona:** Sneha Reddy (C004) · verify first.
1. "I lost my debit card, please block it."
2. "The Visa debit card ending 7788."
3. "It was lost."
4. "Yes, please block it."

**Expect:** routes to **card_agent** → `get_card_list` then `block_card`
(reason `lost`). Success with a **BLK-** reference number.

### B2 — Block a card that's already blocked ⚠️
**Persona:** Sneha Reddy (C004) · verify first.
1. "Please block my RuPay credit card ending 9911."
2. "Yes, block it."

**Expect:** `block_card` returns **"Card is already blocked"** — the agent should tell
you it's already blocked rather than claiming success, and offer further help.

### B3 — Start a block, then cancel 🛑
**Persona:** Sneha Reddy (C004) · verify first.
1. "I want to block my Visa debit card."
2. "Actually, never mind — I found it. Don't block it."

**Expect:** `get_card_list` may be called, but **`block_card` is NOT called**. The agent
confirms it won't block anything.

---

## C. Account access & cheques (Account agent)

### C1 — Account access problems 🔒
**Persona:** Mohammed Khan (C007) · verify first.
1. "I can't access my account, something is wrong."
2. "My savings account."

**Expect:** routes to **account_agent** → `get_account_status` (on ACC009). It should
report multiple issues: **account frozen**, **KYC expired**, **netbanking locked**,
**PIN blocked**, with guidance for each.

### C2 — Stop a cheque ✅
**Persona:** Vikram Singh (C005) · verify first.
1. "I want to stop a cheque payment."
2. "Cheque number 000555, for 30,000 rupees."
3. "Yes, please stop it."

**Expect:** `stop_cheque` succeeds with an **STP-** reference number.

### C3 — Stop a cheque that already cleared ❌
**Persona:** Vikram Singh (C005) · verify first.
1. "Please stop cheque number 000556 for 12,000 rupees."
2. "Yes, stop it."

**Expect:** `stop_cheque` fails with **"Cheque already cleared"** — agent explains it
can't be stopped.

---

## D. Transactions & disputes (Transaction agent)

### D1 — Check balance ✅
**Persona:** Rahul Sharma (C001) · verify first.
1. "What's the balance in my savings account?"
2. "Savings account."

**Expect:** routes to **transaction_agent** → `get_customer_accounts` → `get_balance`.
Agent states the balance (~₹45,230.50).

### D2 — Find a failed transaction and raise a dispute ✅
**Persona:** Rahul Sharma (C001) · verify first.
1. "I see a failed subscription charge of 999 rupees on my savings account."
2. "Savings account."
3. "Please raise a dispute for that failed transaction."
4. "Yes, I confirm — go ahead."

**Expect:** `get_transactions` finds the failed ₹999 subscription (TXN010), then
`raise_dispute` (reason `failed_transaction`) succeeds with a **DSP-** reference.

### D3 — Raise a dispute that already exists ❌
**Persona:** Vikram Singh (C005) · verify first.
1. "There's an unknown online charge of 4,500 rupees on my current account I don't recognise."
2. "Current account."
3. "Please raise a dispute for it."
4. "Yes, go ahead."

**Expect:** `raise_dispute` fails because a dispute is **already open** for that
transaction (TXN015) — agent reads back the existing reference instead of creating a new one.

---

## E. Bills, loans & payments (Payment agent)

### E1 — Pay a bill ✅
**Persona:** Sneha Reddy (C004) · verify first.
1. "I want to pay my water bill."
2. "My savings account."
3. "Pay the City Water Board bill."  *(₹300)*
4. "Yes, pay it."

**Expect:** `get_pending_bills` → `make_payment` succeeds with a **PAY-** reference.
New balance should be **₹50** (₹350 − ₹300).

### E2 — Payment with insufficient funds ❌
**Persona:** Sneha Reddy (C004) · verify first.
*(Run E1 first to make this bite harder, or run fresh — either way ₹3,200 > balance.)*
1. "I want to pay my electricity bill — Reliance Energy."  *(₹3,200)*
2. "My savings account."
3. "Yes, pay it."

**Expect:** `make_payment` fails with **"Insufficient balance"** — the agent apologises
and does NOT deduct anything.

### E3 — Loan details (multiple loans) ✅
**Persona:** Anjali Nair (C006) · verify first.
1. "Can you tell me about my loans?"
2. "Both accounts, please."  *(car loan on savings, education loan on current)*

**Expect:** routes to **payment_agent** → `get_loan_details`. Agent describes the car
loan (~₹4.5L outstanding) and the education loan (~₹9.8L outstanding), EMIs and due dates.

### E4 — Empty state: no bills, no loans 🪹
**Persona:** Deepa Iyer (C008) · verify first.
1. "What bills do I have pending?"
2. "Do I have any active loans?"

**Expect:** `get_pending_bills` and `get_loan_details` both come back **empty**. The
agent should clearly say there are no pending bills and no active loans — gracefully,
without inventing data.

---

## F. Routing, language & escalation

### F1 — Hindi conversation 🌐
**Persona:** Rahul Sharma (C001).
Speak the whole call in Hindi, e.g.:
1. "Mujhe apne savings account ka balance jaanna hai."
2. (verify in Hindi as it asks)
3. "Savings account."

**Expect:** the agent **replies in Hindi**, verifies, routes to transaction_agent, and
reports the balance. Switching languages mid-call should make it switch with you.

### F2 — Out-of-scope request 🚫
**Persona:** any verified persona (e.g. Rahul C001).
1. (after verifying) "I want to open a new fixed deposit account."

**Expect:** the agent recognises this is out of scope, calls `escalate_to_human` with
reason **out_of_scope**, says a human will assist, and ends the session. It should NOT
tell you to visit a branch or use the app.

### F3 — Emotional distress 💔
**Persona:** any verified persona.
1. (after verifying) "Someone has drained all my money, I'm devastated and don't know what to do, please help me."

**Expect:** the agent empathises, calls `escalate_to_human` with reason
**emotional_distress** (with an **ESC-** reference), and ends the session.

### F4 — General "what can you do?" question ℹ️
**Persona:** any verified persona.
1. (after verifying) "What kind of things can you help me with?"

**Expect:** the agent calls `search_knowledge_base` and answers in one or two sentences
about available services — without routing you to a specialist unless you then ask for one.

### F5 — Two tasks in one call (no re-verification) 🔁
**Persona:** Sneha Reddy (C004) · verify first.
1. "Block my Visa debit card ending 7788, it's lost." → "Yes, block it."
2. (after it's done, agent asks "anything else?") "Yes — what's my account balance?"
3. "Savings account."

**Expect:** **card_agent** blocks the card (BLK- ref), control returns to the router,
then **transaction_agent** reports the balance. `verify_identity` is **only called once**
for the whole call.

---

## Quick pass/fail checklist

For each scenario, it "passes" if:
- ✅ The **right specialist** appears in the Agent panel (card / account / transaction / payment).
- ✅ The **expected tool(s)** fire in the Tool Calls panel, in the right order.
- ✅ Success cases return a **reference number**; failure cases return the **expected refusal** (already blocked / cleared / insufficient / duplicate dispute).
- ✅ The agent never leaks IDs, tool names, or other customers' data, and stays in one or two short spoken sentences.

---

## Appendix — Testing by text (no microphone, no STT/TTS cost)

The backend exposes text chat endpoints that run the exact same agents and tools without
voice. Handy for fast iteration. With the backend running on `:8000`:

```bash
# 1. Start a chat session (unverified — agent will verify you, just like a call)
curl -s -X POST localhost:8000/api/chat/start \
  -H 'content-type: application/json' \
  -d '{"llm_provider":"anthropic","language":"en-IN"}'
# → {"session_id":"abcd1234", ...}

# 2. Send a message (repeat with each line from a scenario above)
curl -s -X POST localhost:8000/api/chat/message \
  -H 'content-type: application/json' \
  -d '{"session_id":"abcd1234","message":"I lost my debit card, please block it"}'
# The JSON response shows agent, agent_response, tool_calls, handover_chain, session_state.
```

To skip verification while testing a specific specialist, start pre-verified:

```bash
curl -s -X POST localhost:8000/api/chat/start \
  -H 'content-type: application/json' \
  -d '{"llm_provider":"anthropic","language":"en-IN","pre_verified":true,"customer_id":"C004","customer_name":"Sneha Reddy"}'
```

There's also an automated assertion suite for regression testing — see
`backend/test_chat_api.py` (`cd backend && python test_chat_api.py`).
