# Horizon Bank Voice Agent — Test Transcripts

Speak these lines into the mic to exercise every flow. Speak **digits slowly with small gaps**
("nine… eight… seven…") — fast digit runs are the #1 cause of mis-transcription.

---

## Reset between tests
From the `backend/` folder:

    python reset_db.py

This restores the seed data below. Then start a **new conversation** in the app.

---

## Test customers (for identity verification)
Verify with **full name + mobile number + date of birth** (or your last transaction amount).

| Name          | Mobile        | Date of birth     | Good for testing                                                        |
|---------------|---------------|-------------------|-------------------------------------------------------------------------|
| Rahul Sharma  | 9876543210    | 15 August 1990    | Everything: 2 accounts, an active + an already-blocked card, a failed ₹999 txn, pending bills, a home loan, a cheque |
| Priya Patel   | 9123456789    | 22 March 1985     | Account access: frozen account, locked netbanking, blocked PIN, expired KYC |
| Amit Verma    | 9988776655    | 10 December 1995  | Pending KYC, gas + overdue electricity bills, a stopped cheque, a personal loan |

Rahul's data (for reference): savings a/c balance ₹45,230.50, current a/c ₹1,25,000 ·
Visa **debit** ending **4521** (active), Mastercard **credit** ending **8834** (already blocked) ·
cheque **000123** for ₹15,000 (active), cheque **000124** (already cleared) ·
a **failed ₹999** "Subscription" transaction · electricity bill ₹2,150 to Tata Power · home loan EMI ₹18,500.

---

## Scenario 1 — Verify identity (router)
- You: "Hello."
- Agent greets, asks your full name.
- You: "Rahul Sharma."
- Agent asks for your mobile number.
- You: "nine… eight… seven… six… five… four… three… two… one… zero."
- Agent asks your date of birth.
- You: "fifteenth of August, nineteen ninety."
- ✅ Expect: "Thank you Rahul Sharma, your identity is verified. How can I help you today?"

## Scenario 2 — Block a card (asks WHY, confirms, references)
- You: "I lost my debit card, please block it."
- Agent confirms which card + the reason: "I'll block your Visa debit card ending four five two one as it has been lost — shall I go ahead?"
- You: "Yes, please."
- ✅ Expect: blocks it, reads a reference number, mentions a replacement in 5–7 working days.
- 🔸 Designed-failure variant: "Block my credit card." → it's already blocked; the agent says so.

## Scenario 3 — Check balance (fast; often 0 tool calls)
- You: "What's my account balance?"
- Agent: "Which account — savings or current?"
- You: "Savings."
- ✅ Expect: "Your savings account balance is forty-five thousand two hundred thirty rupees."

## Scenario 4 — Recent transactions + dispute a failed charge (asks WHY)
- You: "Show me my recent transactions."
- Agent lists them.
- You: "There's a nine hundred ninety-nine rupee subscription that failed — I want to dispute it."
- Agent explains the failed txn, asks the reason (failed / unauthorised / duplicate / incorrect amount), confirms.
- You: "It was a failed transaction."  → then "Yes, go ahead."
- ✅ Expect: raises the dispute, reads a reference number.

## Scenario 5 — Account access problem (verify as Priya)
- Verify as **Priya Patel / 9123456789 / 22 March 1985**.
- You: "I can't log into my netbanking."
- ✅ Expect (account agent): explains the account is frozen / netbanking locked / KYC expired and how to fix it. (Will NOT read your balance — that's a different area.)

## Scenario 6 — Stop a cheque (asks WHY + amount, confirms)
- (as Rahul) You: "I want to stop a cheque."
- Agent asks the cheque number.
- You: "cheque number one two three."
- Agent asks the reason and the amount.
- You: "fifteen thousand rupees, I lost the cheque."
- ✅ Expect: confirms, stops it, reads a reference.
- 🔸 Designed-failure variant: stop cheque "one two four" → already cleared; can't be stopped.

## Scenario 7 — Pay a bill (confirms before moving money)
- You: "I want to pay my electricity bill."
- Agent names the Tata Power bill of ₹2,150 and asks to confirm.
- You: "Yes, pay it."
- ✅ Expect: pays it, reads a reference number and your new balance.

## Scenario 8 — Loan / EMI details
- You: "Tell me about my loan."
- ✅ Expect: home loan, outstanding ~₹18.5 lakh, EMI ₹18,500, next due date — in plain words.

## Scenario 9 — General question (knowledge base / RAG)
- You: "What can you help me with?"  or  "Do you offer fund transfers?"
- ✅ Expect: a natural 1–2 sentence answer from the knowledge base; if it's out of scope, it escalates.

## Scenario 10 — Out of scope → human (escalation)
- You: "I want to transfer money to my friend's account."
- ✅ Expect: it apologises, escalates to a human with a reference number, ends the call.

## Scenario 11 — Emotional distress → human (escalation)
- You: "I am so frustrated, nothing is working and I'm really upset!"
- ✅ Expect: sincere empathy first, then escalation to a human agent.

## Scenario 12 — Language switch mid-call (Hindi)
- You (English): "What is my balance?"  → answer in English.
- You (next turn, Hindi): "मेरा क्रेडिट कार्ड ब्लॉक कर दीजिये।"
- ✅ Expect: the agent switches to Hindi and continues the card-block flow in Hindi.

## Scenario 13 — End the call (the rating prompt)
- You: "No, that's all. Thank you."
- ✅ Expect: "Thank you for banking with Horizon Bank. Please rate this call on the SMS we've sent you. Have a wonderful day." → call ends.

---

## Known failure cases (what to expect / be careful of)

**Things that can genuinely go wrong while testing:**
1. **STT mishears a number → verification fails.** Sarvam can drop/swap a digit in a fast spoken number (e.g. 9876543210 → 976543210). If it says it can't verify you, it's almost always a misheard number, not a logic bug. *Fix:* say digits slowly with gaps, or verify by **date of birth** (more robust than the 10-digit number).
2. **Escalation occasionally spoken instead of executed.** GPT-OSS sometimes writes the escalate-to-human call as text rather than a real tool call. The brace-filter hides the raw JSON, so you won't see garbage — but in that one instance the escalation reference may not be a real one. Intermittent.
3. **Language can flip on a noise.** A cough or laugh transcribed as Hindi/English can flip that one reply's language.
4. **Pre-fetched balance can be one step stale right after a payment.** If you pay a bill then immediately ask the balance, the agent may quote the pre-call figure; ask again and it re-fetches.
5. **Barge-in on a long reply** adds a short pause before the next answer (the TTS stream drains/reconnects).

**Designed "failures" (correct behaviour, not bugs):** already-blocked card, already-cleared cheque (can't stop), an existing dispute (can't re-raise), insufficient balance for a payment, out-of-scope / emotional requests (→ human). The agent will tell you plainly.

**Demo-grade gaps (from the earlier audit — fine for single-user testing, would matter for production):**
- The `/api/chat/*` REST endpoints have **no authentication** and accept a `pre_verified` flag (identity bypass) — not used by the voice flow, but exposed.
- `make_payment` is **not transaction-atomic** — two concurrent payments on one account could race.
- Reference numbers are **random** (rare collisions possible).
- Verification accepts **first-name + DOB with no lockout/rate-limit**.
- All sessions share **one DB connection** (fine for one user; not for load).
