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


def build_registry(db) -> ToolRegistry:
    from .verify_tools import make_verify_identity
    from .card_tools import make_get_card_list, make_block_card
    from .account_tools import make_get_account_status, make_stop_cheque
    from .transaction_tools import make_get_balance, make_get_customer_accounts, make_get_transactions, make_get_txn_status, make_raise_dispute
    from .payment_tools import make_get_pending_bills, make_get_loan_details, make_make_payment

    registry = ToolRegistry()

    registry.register(ToolDefinition(
        name="verify_identity",
        description="Verifies customer identity using their registered mobile number and a verification answer (date of birth in DD-MM-YYYY format or last transaction amount).",
        parameters={
            "type": "object",
            "properties": {
                "mobile_number": {"type": "string", "description": "The customer's registered mobile number"},
                "verification_answer": {"type": "string", "description": "Customer's DOB (DD-MM-YYYY) or last txn amount"},
            },
            "required": ["mobile_number", "verification_answer"],
        },
        handler=make_verify_identity(db),
    ))

    registry.register(ToolDefinition(
        name="get_card_list",
        description="Returns all debit and credit cards linked to the customer's account, including card type, network, last four digits, and current status.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "The verified customer ID"},
            },
            "required": ["customer_id"],
        },
        handler=make_get_card_list(db),
    ))

    registry.register(ToolDefinition(
        name="block_card",
        description="Blocks a debit or credit card immediately. Use this after the customer has explicitly confirmed they want to block the card. Returns a reference number for tracking.",
        parameters={
            "type": "object",
            "properties": {
                "card_id": {"type": "string", "description": "The card ID to block"},
                "reason": {"type": "string", "description": "Reason for blocking: lost, stolen, or suspicious_activity"},
            },
            "required": ["card_id", "reason"],
        },
        handler=make_block_card(db),
    ))

    registry.register(ToolDefinition(
        name="get_account_status",
        description="Returns the current status of a bank account including balance, netbanking status, debit card PIN status, KYC status, and any active issues or blocks.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The bank account ID"},
            },
            "required": ["account_id"],
        },
        handler=make_get_account_status(db),
    ))

    registry.register(ToolDefinition(
        name="stop_cheque",
        description="Stops a cheque payment. Use after the customer confirms the cheque number and amount. Returns a reference number.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The bank account ID"},
                "cheque_number": {"type": "string", "description": "The cheque number to stop"},
                "amount": {"type": "number", "description": "The cheque amount for verification"},
            },
            "required": ["account_id", "cheque_number", "amount"],
        },
        handler=make_stop_cheque(db),
    ))

    registry.register(ToolDefinition(
        name="get_customer_accounts",
        description="Returns all bank accounts linked to a customer, including account type, balance, and status. Use this first to find the account ID before calling other account-specific tools.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "The verified customer ID"},
            },
            "required": ["customer_id"],
        },
        handler=make_get_customer_accounts(db),
    ))

    registry.register(ToolDefinition(
        name="get_balance",
        description="Returns the current balance of a bank account along with account type and status.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The bank account ID"},
            },
            "required": ["account_id"],
        },
        handler=make_get_balance(db),
    ))

    registry.register(ToolDefinition(
        name="get_transactions",
        description="Returns the most recent transactions for a bank account, including amount, type, description, and status.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The bank account ID"},
                "count": {"type": "integer", "description": "Number of recent transactions to return. Defaults to 5."},
            },
            "required": ["account_id"],
        },
        handler=make_get_transactions(db),
    ))

    registry.register(ToolDefinition(
        name="get_txn_status",
        description="Checks the detailed status of a specific transaction, including any dispute or reversal information.",
        parameters={
            "type": "object",
            "properties": {
                "txn_id": {"type": "string", "description": "The transaction ID to check"},
            },
            "required": ["txn_id"],
        },
        handler=make_get_txn_status(db),
    ))

    registry.register(ToolDefinition(
        name="raise_dispute",
        description="Raises a dispute for a transaction. Use after the customer has explicitly confirmed they want to dispute the transaction. Returns a reference number.",
        parameters={
            "type": "object",
            "properties": {
                "txn_id": {"type": "string", "description": "The transaction ID to dispute"},
                "reason": {"type": "string", "description": "Reason for the dispute: failed_transaction, unauthorized_charge, duplicate_charge, or incorrect_amount"},
            },
            "required": ["txn_id", "reason"],
        },
        handler=make_raise_dispute(db),
    ))

    registry.register(ToolDefinition(
        name="get_pending_bills",
        description="Returns all pending and overdue bills for a bank account, including biller name, amount, due date, and bill type.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The bank account ID"},
            },
            "required": ["account_id"],
        },
        handler=make_get_pending_bills(db),
    ))

    registry.register(ToolDefinition(
        name="get_loan_details",
        description="Returns active loan details for a bank account including loan type, outstanding amount, EMI amount, interest rate, and next due date.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The bank account ID"},
            },
            "required": ["account_id"],
        },
        handler=make_get_loan_details(db),
    ))

    registry.register(ToolDefinition(
        name="make_payment",
        description="Makes a bill or EMI payment from the customer's account. Use after the customer has explicitly confirmed the payment. Returns a reference number.",
        parameters={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The bank account ID to pay from"},
                "biller_id": {"type": "string", "description": "The biller ID to pay to"},
                "amount": {"type": "number", "description": "The payment amount"},
            },
            "required": ["account_id", "biller_id", "amount"],
        },
        handler=make_make_payment(db),
    ))

    return registry
