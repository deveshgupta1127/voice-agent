from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict
    handler: Callable


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool_def: ToolDefinition) -> None:
        self._tools[tool_def.name] = tool_def

    def get_definitions(self, tool_names: list[str]) -> list[dict]:
        defs = []
        for name in tool_names:
            if name in self._tools:
                t = self._tools[name]
                defs.append({
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                })
        return defs

    async def execute(self, tool_name: str, args: dict) -> Any:
        if tool_name not in self._tools:
            raise KeyError(f"Tool '{tool_name}' not registered")
        return await self._tools[tool_name].handler(**args)


def build_registry(db, rag=None) -> ToolRegistry:
    from .verify_tools import make_verify_identity
    from .card_tools import make_get_card_list, make_block_card
    from .account_tools import make_get_account_status, make_stop_cheque
    from .transaction_tools import make_get_balance, make_get_customer_accounts, make_get_transactions, make_get_txn_status, make_raise_dispute
    from .payment_tools import make_get_pending_bills, make_get_loan_details, make_make_payment
    from .escalation_tools import make_escalate_to_human
    from .rag_tools import make_search_knowledge_base

    registry = ToolRegistry()

    registry.register(ToolDefinition(
        name="verify_identity",
        description="Verifies customer identity using their name, registered mobile number, and a verification answer. The answer can be a date of birth (any spoken format — the system normalizes it) or the amount of their last completed transaction. Call this during the verification step before any banking operations. All three parameters are required.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The customer's name as they said it (e.g. 'Rahul' or 'Rahul Sharma'). First name alone is accepted."},
                "mobile_number": {"type": "string", "description": "The customer's 10-digit registered mobile number, digits only (e.g. 9876543210)"},
                "verification_answer": {"type": "string", "description": "Customer's date of birth (any format, e.g. '15-08-1990' or 'August 15 1990') OR their last transaction amount as a number string (e.g. '2500')"},
            },
            "required": ["name", "mobile_number", "verification_answer"],
        },
        handler=make_verify_identity(db),
    ))

    registry.register(ToolDefinition(
        name="get_card_list",
        description="Returns all debit and credit cards linked to the customer. Use this as the first step when handling card blocking requests — it returns card_id, card_type, card_network, last_four, status, and expiry for each card. Do NOT use this for balance or transaction queries.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "The verified customer ID (e.g. C001)"},
            },
            "required": ["customer_id"],
        },
        handler=make_get_card_list(db),
    ))

    registry.register(ToolDefinition(
        name="block_card",
        description="Permanently blocks a debit or credit card. This action is irreversible — only call after the customer has explicitly confirmed. Requires the card_id from a prior get_card_list call and a reason. Returns a reference number (e.g. BLK-20260618-123) that the customer should note down.",
        parameters={
            "type": "object",
            "properties": {
                "card_id": {"type": "string", "description": "The card ID to block (from get_card_list result, e.g. CARD001). Never ask the customer for this — look it up."},
                "reason": {"type": "string", "description": "Why the card is being blocked. Must be one of: lost, stolen, suspicious_activity"},
            },
            "required": ["card_id", "reason"],
        },
        handler=make_block_card(db),
    ))

    registry.register(ToolDefinition(
        name="get_account_status",
        description="Checks an account for access problems: frozen status, locked netbanking, blocked PIN, expired KYC. Use ONLY when the customer reports an access issue — NOT for balance inquiries or general account info. Returns an issues array listing each problem with severity and resolution steps.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The bank account ID (e.g. ACC001). Get this from get_customer_accounts first."},
            },
            "required": ["account_id"],
        },
        handler=make_get_account_status(db),
    ))

    registry.register(ToolDefinition(
        name="stop_cheque",
        description="Stops a cheque payment to prevent it from being encashed. Only call after the customer confirms the cheque number and amount match. Returns a reference number. Will fail if the cheque is already cleared or already stopped.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The bank account ID the cheque belongs to"},
                "cheque_number": {"type": "string", "description": "The cheque number to stop (e.g. 000123)"},
                "amount": {"type": "number", "description": "The cheque amount for verification — must match the amount on record"},
            },
            "required": ["account_id", "cheque_number", "amount"],
        },
        handler=make_stop_cheque(db),
    ))

    registry.register(ToolDefinition(
        name="get_customer_accounts",
        description="Returns all bank accounts (savings, current) linked to a customer. MUST be called first before any account-specific tool (get_balance, get_transactions, get_pending_bills, get_loan_details, get_account_status) because those tools need an account_id which this tool provides. Returns account_id, account_type, balance, and status for each account.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "The verified customer ID (e.g. C001)"},
            },
            "required": ["customer_id"],
        },
        handler=make_get_customer_accounts(db),
    ))

    registry.register(ToolDefinition(
        name="get_balance",
        description="Returns the current balance of a specific bank account. Use when the customer asks 'what is my balance', 'how much money do I have', or 'check my balance'. Takes an account_id from a prior get_customer_accounts call. Returns account_id, account_type, balance, and status.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The bank account ID (e.g. ACC001). Get this from get_customer_accounts first."},
            },
            "required": ["account_id"],
        },
        handler=make_get_balance(db),
    ))

    registry.register(ToolDefinition(
        name="get_transactions",
        description="Returns the N most recent transactions for a bank account. Use when the customer asks about recent transactions, transaction history, wants to find a specific transaction, or reports a failed/unexpected charge. Each transaction includes txn_id, amount, txn_type (credit/debit), description, status (completed/failed/reversed), and date.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The bank account ID (e.g. ACC001). Get this from get_customer_accounts first."},
                "count": {"type": "integer", "description": "Number of recent transactions to return. Defaults to 5. Use a higher number if the customer is looking for an older transaction."},
            },
            "required": ["account_id"],
        },
        handler=make_get_transactions(db),
    ))

    registry.register(ToolDefinition(
        name="get_txn_status",
        description="Gets detailed status of one specific transaction, including whether a dispute has been raised. Use ONLY after identifying the specific transaction from get_transactions results. Do NOT call this without first calling get_transactions to find the txn_id. Returns transaction details plus dispute info (status, reference, reason) if a dispute exists.",
        parameters={
            "type": "object",
            "properties": {
                "txn_id": {"type": "string", "description": "The transaction ID to check (e.g. TXN010). Get this from get_transactions result — never ask the customer for it."},
            },
            "required": ["txn_id"],
        },
        handler=make_get_txn_status(db),
    ))

    registry.register(ToolDefinition(
        name="raise_dispute",
        description="Raises a formal dispute for a transaction (failed, unauthorized, duplicate, or incorrect amount). This creates a case that the bank will investigate. Only call after explicit customer confirmation. Will fail if a dispute already exists for this transaction. Returns a reference number (e.g. DSP-20260618-123).",
        parameters={
            "type": "object",
            "properties": {
                "txn_id": {"type": "string", "description": "The transaction ID to dispute (from get_transactions result — never ask the customer for it)"},
                "reason": {"type": "string", "description": "Must be one of: failed_transaction, unauthorized_charge, duplicate_charge, incorrect_amount"},
            },
            "required": ["txn_id", "reason"],
        },
        handler=make_raise_dispute(db),
    ))

    registry.register(ToolDefinition(
        name="get_pending_bills",
        description="Returns all unpaid bills and overdue bills for a bank account. Use when the customer wants to pay a bill or see what bills are due. Each bill includes bill_id, biller_name, biller_id (needed for make_payment), bill_type (electricity/water/gas/insurance/emi), amount, due_date, and status (pending/overdue). Do NOT use this to check balance or transactions.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The bank account ID (e.g. ACC001). Get this from get_customer_accounts first."},
            },
            "required": ["account_id"],
        },
        handler=make_get_pending_bills(db),
    ))

    registry.register(ToolDefinition(
        name="get_loan_details",
        description="Returns details of all active loans linked to a bank account. Use when the customer asks about their loan, EMI amount, outstanding balance, or next due date. Returns loan_type (home/personal/car/education), principal, outstanding, emi_amount, interest_rate, tenure_months, next_due_date, and status.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The bank account ID (e.g. ACC001). Get this from get_customer_accounts first."},
            },
            "required": ["account_id"],
        },
        handler=make_get_loan_details(db),
    ))

    registry.register(ToolDefinition(
        name="make_payment",
        description="Pays a pending bill or EMI from the customer's account. This deducts money from the account — only call after explicit customer confirmation. Requires the biller_id from a prior get_pending_bills call (never ask the customer for biller_id). Checks that the amount matches the bill and that the account has sufficient balance. Returns a reference number and the new account balance.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The bank account ID to debit (e.g. ACC001)"},
                "biller_id": {"type": "string", "description": "The biller ID from get_pending_bills result (e.g. BP001). Never ask the customer for this."},
                "amount": {"type": "number", "description": "The exact bill amount to pay — must match the bill amount on record"},
            },
            "required": ["account_id", "biller_id", "amount"],
        },
        handler=make_make_payment(db),
    ))

    registry.register(ToolDefinition(
        name="escalate_to_human",
        description="Escalates the call to a human agent when no automated agent can help, or when the customer is in emotional distress. Returns a reference number for tracking. Use this instead of telling the customer to visit a branch.",
        parameters={
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why the call is being escalated. Must be one of: out_of_scope, emotional_distress, verification_failed, customer_request, complex_issue"},
                "summary": {"type": "string", "description": "Brief summary of the customer's issue and what has been attempted so far"},
            },
            "required": ["reason", "summary"],
        },
        handler=make_escalate_to_human(),
    ))

    if rag is not None:
        registry.register(ToolDefinition(
            name="search_knowledge_base",
            description="Searches Horizon Bank's knowledge base to answer general customer questions about available services, policies, and procedures. Use this when the customer asks a general question like 'what can you help me with', 'do you offer fund transfers', 'how does card blocking work', or any question about what services are available. Do NOT use this for performing actual banking operations — use the routing table for that.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The customer's question in plain English, e.g. 'can I transfer money' or 'what happens when I block my card'"},
                },
                "required": ["query"],
            },
            handler=make_search_knowledge_base(rag),
        ))

    return registry
