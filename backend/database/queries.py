import aiosqlite


async def get_customer_by_mobile(db: aiosqlite.Connection, mobile: str) -> dict | None:
    cursor = await db.execute("SELECT * FROM customers WHERE mobile = ?", (mobile,))
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def get_cards_by_customer(db: aiosqlite.Connection, customer_id: str) -> list[dict]:
    cursor = await db.execute(
        "SELECT card_id, card_type, card_network, last_four, status, expiry FROM cards WHERE customer_id = ?",
        (customer_id,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def update_card_status(
    db: aiosqlite.Connection,
    card_id: str,
    status: str,
    reason: str,
    reference: str,
) -> bool:
    cursor = await db.execute(
        "UPDATE cards SET status = ?, blocked_reason = ?, blocked_at = datetime('now'), block_ref = ? WHERE card_id = ?",
        (status, reason, reference, card_id),
    )
    await db.commit()
    return cursor.rowcount > 0


async def get_account(db: aiosqlite.Connection, account_id: str) -> dict | None:
    cursor = await db.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,))
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def get_accounts_by_customer(db: aiosqlite.Connection, customer_id: str) -> list[dict]:
    cursor = await db.execute("SELECT * FROM accounts WHERE customer_id = ?", (customer_id,))
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_cheque(db: aiosqlite.Connection, account_id: str, cheque_number: str) -> dict | None:
    cursor = await db.execute(
        "SELECT * FROM cheques WHERE account_id = ? AND cheque_number = ?",
        (account_id, cheque_number),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def update_cheque_status(
    db: aiosqlite.Connection,
    cheque_id: str,
    status: str,
    reference: str,
) -> bool:
    cursor = await db.execute(
        "UPDATE cheques SET status = ?, stopped_at = datetime('now'), stop_ref = ? WHERE cheque_id = ?",
        (status, reference, cheque_id),
    )
    await db.commit()
    return cursor.rowcount > 0


async def get_last_transaction(db: aiosqlite.Connection, account_id: str) -> dict | None:
    cursor = await db.execute(
        "SELECT amount, txn_type, description, created_at FROM transactions WHERE account_id = ? AND status = 'completed' ORDER BY created_at DESC LIMIT 1",
        (account_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def get_recent_transactions(db: aiosqlite.Connection, account_id: str, count: int = 5) -> list[dict]:
    cursor = await db.execute(
        "SELECT txn_id, amount, txn_type, description, status, created_at FROM transactions WHERE account_id = ? ORDER BY created_at DESC LIMIT ?",
        (account_id, count),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_transaction(db: aiosqlite.Connection, txn_id: str) -> dict | None:
    cursor = await db.execute("SELECT * FROM transactions WHERE txn_id = ?", (txn_id,))
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def get_dispute_by_txn(db: aiosqlite.Connection, txn_id: str) -> dict | None:
    cursor = await db.execute(
        "SELECT * FROM disputes WHERE txn_id = ? ORDER BY raised_at DESC LIMIT 1",
        (txn_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def insert_dispute(
    db: aiosqlite.Connection,
    dispute_id: str,
    txn_id: str,
    account_id: str,
    reason: str,
    reference: str,
) -> None:
    await db.execute(
        "INSERT INTO disputes (dispute_id, txn_id, account_id, reason, status, reference) VALUES (?, ?, ?, ?, 'open', ?)",
        (dispute_id, txn_id, account_id, reason, reference),
    )
    await db.commit()


async def get_pending_bills_by_account(db: aiosqlite.Connection, account_id: str) -> list[dict]:
    cursor = await db.execute(
        "SELECT bill_id, biller_name, biller_id, bill_type, amount, due_date, status FROM bills WHERE account_id = ? AND status IN ('pending', 'overdue') ORDER BY due_date ASC",
        (account_id,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_loans_by_account(db: aiosqlite.Connection, account_id: str) -> list[dict]:
    cursor = await db.execute(
        "SELECT loan_id, loan_type, principal, outstanding, emi_amount, interest_rate, tenure_months, next_due_date, status FROM loans WHERE account_id = ? AND status = 'active'",
        (account_id,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_bill_by_biller(db: aiosqlite.Connection, account_id: str, biller_id: str) -> dict | None:
    cursor = await db.execute(
        "SELECT * FROM bills WHERE account_id = ? AND biller_id = ? AND status IN ('pending', 'overdue') LIMIT 1",
        (account_id, biller_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def update_bill_paid(db: aiosqlite.Connection, bill_id: str, reference: str) -> bool:
    cursor = await db.execute(
        "UPDATE bills SET status = 'paid', paid_at = datetime('now'), payment_ref = ? WHERE bill_id = ?",
        (reference, bill_id),
    )
    await db.commit()
    return cursor.rowcount > 0


async def update_account_balance(db: aiosqlite.Connection, account_id: str, new_balance: float) -> bool:
    cursor = await db.execute(
        "UPDATE accounts SET balance = ? WHERE account_id = ?",
        (new_balance, account_id),
    )
    await db.commit()
    return cursor.rowcount > 0
