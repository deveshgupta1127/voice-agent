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

    return registry
