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
