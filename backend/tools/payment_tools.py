import datetime
import random
from database.queries import (
    get_account,
    get_pending_bills_by_account,
    get_loans_by_account,
    get_bill_by_biller,
    update_bill_paid,
    update_account_balance,
)


def make_get_pending_bills(db):
    async def get_pending_bills(account_id: str) -> dict:
        account = await get_account(db, account_id)
        if account is None:
            return {"error": "Account not found"}

        bills = await get_pending_bills_by_account(db, account_id)
        return {"account_id": account_id, "bills": bills}

    return get_pending_bills


def make_get_loan_details(db):
    async def get_loan_details(account_id: str) -> dict:
        account = await get_account(db, account_id)
        if account is None:
            return {"error": "Account not found"}

        loans = await get_loans_by_account(db, account_id)
        return {"account_id": account_id, "loans": loans}

    return get_loan_details


def make_make_payment(db):
    async def make_payment(account_id: str, biller_id: str, amount: float) -> dict:
        account = await get_account(db, account_id)
        if account is None:
            return {"success": False, "reason": "Account not found"}

        if account["status"] != "active":
            return {"success": False, "reason": "Account is not active"}

        bill = await get_bill_by_biller(db, account_id, biller_id)
        if bill is None:
            return {"success": False, "reason": "No pending bill found for this biller"}

        if bill["status"] == "paid":
            return {"success": False, "reason": "This bill has already been paid"}

        if abs(bill["amount"] - amount) > 0.01:
            return {
                "success": False,
                "reason": f"Amount mismatch. Bill amount is ₹{bill['amount']:,.2f}",
            }

        if account["balance"] < amount:
            return {"success": False, "reason": "Insufficient balance"}

        today = datetime.date.today().strftime("%Y%m%d")
        ref = f"PAY-{today}-{random.randint(100, 999)}"

        await update_bill_paid(db, bill["bill_id"], ref)
        await update_account_balance(db, account_id, account["balance"] - amount)

        return {
            "success": True,
            "biller_name": bill["biller_name"],
            "amount": amount,
            "reference_number": ref,
            "paid_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "new_balance": round(account["balance"] - amount, 2),
            "message": f"Payment of ₹{amount:,.2f} to {bill['biller_name']} completed successfully.",
        }

    return make_payment
