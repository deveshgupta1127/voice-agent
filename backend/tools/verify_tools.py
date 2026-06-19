import re
from database.queries import get_customer_by_mobile, get_accounts_by_customer, get_last_transaction


MONTH_MAP = {
    "january": "01", "jan": "01",
    "february": "02", "feb": "02",
    "march": "03", "mar": "03",
    "april": "04", "apr": "04",
    "may": "05",
    "june": "06", "jun": "06",
    "july": "07", "jul": "07",
    "august": "08", "aug": "08",
    "september": "09", "sep": "09", "sept": "09",
    "october": "10", "oct": "10",
    "november": "11", "nov": "11",
    "december": "12", "dec": "12",
}


def normalize_date(raw: str) -> str | None:
    text = raw.strip().lower()
    text = re.sub(r"\b(i was born|born on|born in|my date of birth is|my dob is|date of birth|of)\b", "", text)
    text = re.sub(r"(st|nd|rd|th)\b", "", text)
    text = text.strip()

    month_num = None
    for name, num in MONTH_MAP.items():
        if name in text:
            month_num = num
            text = text.replace(name, " ")
            break

    numbers = re.findall(r"\d+", text)

    if month_num is not None and len(numbers) == 2:
        a, b = numbers
        if len(b) == 4:
            return f"{int(a):02d}-{month_num}-{b}"
        if len(a) == 4:
            return f"{int(b):02d}-{month_num}-{a}"
        year = b if len(b) == 4 else f"19{b}" if int(b) > 25 else f"20{b}"
        return f"{int(a):02d}-{month_num}-{year}"

    if len(numbers) == 3:
        a, b, c = numbers

        if len(c) == 4 and int(a) <= 31 and int(b) <= 12:
            return f"{int(a):02d}-{int(b):02d}-{c}"

        if len(c) == 4 and int(b) <= 31 and int(a) <= 12:
            return f"{int(b):02d}-{int(a):02d}-{c}"

        if len(a) == 4 and int(b) <= 12 and int(c) <= 31:
            return f"{int(c):02d}-{int(b):02d}-{a}"

        if int(a) <= 31 and int(b) <= 12:
            year = c if len(c) == 4 else f"19{c}" if int(c) > 25 else f"20{c}"
            return f"{int(a):02d}-{int(b):02d}-{year}"

    return None


def dates_match(stored_dob: str, user_input: str) -> bool:
    if stored_dob.strip() == user_input.strip():
        return True

    normalized = normalize_date(user_input)
    if normalized and normalized == stored_dob:
        return True

    stored_normalized = normalize_date(stored_dob)
    if stored_normalized and normalized and stored_normalized == normalized:
        return True

    return False


def make_verify_identity(db):
    async def verify_identity(mobile_number: str, verification_answer: str) -> dict:
        customer = await get_customer_by_mobile(db, mobile_number)
        if customer is None:
            return {"verified": False, "reason": "Customer not found with this mobile number"}

        if dates_match(customer["dob"], verification_answer):
            return {
                "verified": True,
                "customer_id": customer["customer_id"],
                "customer_name": customer["name"],
            }

        accounts = await get_accounts_by_customer(db, customer["customer_id"])
        for account in accounts:
            last_txn = await get_last_transaction(db, account["account_id"])
            if last_txn:
                txn_amount = str(last_txn["amount"])
                answer_clean = re.sub(r"[^\d.]", "", verification_answer)
                if txn_amount == answer_clean or str(int(float(txn_amount))) == answer_clean:
                    return {
                        "verified": True,
                        "customer_id": customer["customer_id"],
                        "customer_name": customer["name"],
                    }

        return {"verified": False, "reason": "Verification answer does not match our records"}

    return verify_identity
