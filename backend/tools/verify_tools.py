from database.queries import get_customer_by_mobile, get_accounts_by_customer, get_last_transaction


def make_verify_identity(db):
    async def verify_identity(mobile_number: str, verification_answer: str) -> dict:
        customer = await get_customer_by_mobile(db, mobile_number)
        if customer is None:
            return {"verified": False, "reason": "Customer not found"}

        if verification_answer == customer["dob"]:
            return {
                "verified": True,
                "customer_id": customer["customer_id"],
                "customer_name": customer["name"],
            }

        accounts = await get_accounts_by_customer(db, customer["customer_id"])
        for account in accounts:
            last_txn = await get_last_transaction(db, account["account_id"])
            if last_txn and str(last_txn["amount"]) == verification_answer:
                return {
                    "verified": True,
                    "customer_id": customer["customer_id"],
                    "customer_name": customer["name"],
                }

        return {"verified": False, "reason": "Verification answer does not match"}

    return verify_identity
