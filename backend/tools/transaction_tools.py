import datetime
import random
from database.queries import (
    get_account,
    get_accounts_by_customer,
    get_recent_transactions,
    get_transaction,
    get_dispute_by_txn,
    insert_dispute,
)


def make_get_balance(db):
    async def get_balance(account_id: str) -> dict:
        account = await get_account(db, account_id)
        if account is None:
            return {"error": "Account not found"}

        return {
            "account_id": account["account_id"],
            "account_type": account["account_type"],
            "balance": account["balance"],
            "status": account["status"],
        }

    return get_balance


def make_get_customer_accounts(db):
    async def get_customer_accounts(customer_id: str) -> dict:
        accounts = await get_accounts_by_customer(db, customer_id)
        if not accounts:
            return {"error": "No accounts found for this customer"}

        return {
            "accounts": [
                {
                    "account_id": a["account_id"],
                    "account_type": a["account_type"],
                    "balance": a["balance"],
                    "status": a["status"],
                }
                for a in accounts
            ]
        }

    return get_customer_accounts


def make_get_transactions(db):
    async def get_transactions(account_id: str, count: int = 5) -> dict:
        account = await get_account(db, account_id)
        if account is None:
            return {"error": "Account not found"}

        txns = await get_recent_transactions(db, account_id, count)
        return {"account_id": account_id, "transactions": txns}

    return get_transactions


def make_get_txn_status(db):
    async def get_txn_status(txn_id: str) -> dict:
        txn = await get_transaction(db, txn_id)
        if txn is None:
            return {"error": "Transaction not found"}

        dispute = await get_dispute_by_txn(db, txn_id)

        result = {
            "txn_id": txn["txn_id"],
            "amount": txn["amount"],
            "txn_type": txn["txn_type"],
            "description": txn["description"],
            "status": txn["status"],
            "date": txn["created_at"],
        }

        if dispute:
            result["dispute"] = {
                "dispute_id": dispute["dispute_id"],
                "status": dispute["status"],
                "reference": dispute["reference"],
                "reason": dispute["reason"],
                "raised_at": dispute["raised_at"],
            }
        else:
            result["dispute"] = None

        return result

    return get_txn_status


def make_raise_dispute(db):
    async def raise_dispute(txn_id: str, reason: str) -> dict:
        txn = await get_transaction(db, txn_id)
        if txn is None:
            return {"success": False, "reason": "Transaction not found"}

        existing = await get_dispute_by_txn(db, txn_id)
        if existing:
            return {
                "success": False,
                "reason": f"A dispute is already {existing['status']} for this transaction. Reference: {existing['reference']}",
            }

        today = datetime.date.today().strftime("%Y%m%d")
        ref = f"DSP-{today}-{random.randint(100, 999)}"
        dispute_id = f"D{random.randint(1000, 9999)}"

        await insert_dispute(db, dispute_id, txn_id, txn["account_id"], reason, ref)

        return {
            "success": True,
            "dispute_id": dispute_id,
            "txn_id": txn_id,
            "reference_number": ref,
            "raised_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "message": f"Dispute raised for transaction of ₹{txn['amount']:,.2f}. Reference number is {ref}.",
        }

    return raise_dispute
