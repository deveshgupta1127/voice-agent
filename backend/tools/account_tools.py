import datetime
import random
from database.queries import get_account, get_cheque, update_cheque_status


def make_get_account_status(db):
    async def get_account_status(account_id: str) -> dict:
        account = await get_account(db, account_id)
        if account is None:
            return {"error": "Account not found"}

        issues = []
        if account["status"] == "frozen":
            issues.append({
                "type": "account_frozen",
                "message": "Your account is currently frozen. Please visit your nearest branch.",
                "severity": "critical",
            })
        if account["kyc_status"] == "expired":
            issues.append({
                "type": "kyc_expired",
                "message": "Your KYC documents have expired. Please update your KYC at the branch.",
                "severity": "critical",
            })
        elif account["kyc_status"] == "pending":
            issues.append({
                "type": "kyc_pending",
                "message": f"KYC verification is pending. Expiry date: {account['kyc_expiry']}.",
                "severity": "warning",
            })
        if account["netbanking_status"] == "locked":
            issues.append({
                "type": "netbanking_locked",
                "message": "Net banking access is locked. Visit branch or call support to unlock.",
                "severity": "warning",
            })
        if account["debit_card_pin"] == "blocked":
            issues.append({
                "type": "pin_blocked",
                "message": "Debit card PIN is blocked due to multiple wrong attempts. Visit ATM or branch to reset.",
                "severity": "warning",
            })

        return {
            "account_id": account["account_id"],
            "account_type": account["account_type"],
            "status": account["status"],
            "balance": account["balance"],
            "netbanking_status": account["netbanking_status"],
            "debit_card_pin_status": account["debit_card_pin"],
            "kyc_status": account["kyc_status"],
            "issues": issues,
        }

    return get_account_status


def make_stop_cheque(db):
    async def stop_cheque(account_id: str, cheque_number: str, amount: float) -> dict:
        cheque = await get_cheque(db, account_id, cheque_number)
        if cheque is None:
            return {"success": False, "reason": "Cheque not found"}

        if cheque["status"] == "cleared":
            return {"success": False, "reason": "Cheque already cleared"}

        if cheque["status"] == "stopped":
            return {"success": False, "reason": "Cheque is already stopped"}

        if cheque["amount"] is not None and abs(cheque["amount"] - amount) > 0.01:
            return {"success": False, "reason": "Amount does not match cheque records"}

        today = datetime.date.today().strftime("%Y%m%d")
        ref = f"STP-{today}-{random.randint(100, 999)}"

        updated = await update_cheque_status(db, cheque["cheque_id"], "stopped", ref)
        if not updated:
            return {"success": False, "reason": "Failed to stop cheque"}

        return {
            "success": True,
            "cheque_number": cheque_number,
            "amount": amount,
            "reference_number": ref,
            "stopped_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "message": f"Cheque number {cheque_number} for ₹{amount:,.2f} has been stopped.",
        }

    return stop_cheque
