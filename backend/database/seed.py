import aiosqlite


async def seed_database(db: aiosqlite.Connection) -> None:
    await db.executemany(
        "INSERT INTO customers (customer_id, name, mobile, dob, email, language_pref) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("C001", "Rahul Sharma", "9876543210", "15-08-1990", "rahul@example.com", "hi-IN"),
            ("C002", "Priya Patel", "9123456789", "22-03-1985", "priya@example.com", "en-IN"),
            ("C003", "Amit Verma", "9988776655", "10-12-1995", "amit@example.com", "hi-IN"),
        ],
    )

    await db.executemany(
        "INSERT INTO accounts (account_id, customer_id, account_type, balance, status, netbanking_status, debit_card_pin, kyc_status, kyc_expiry) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("ACC001", "C001", "savings", 45230.50, "active", "active", "active", "verified", "2027-08-15"),
            ("ACC002", "C001", "current", 125000.00, "active", "active", "active", "verified", "2027-08-15"),
            ("ACC003", "C002", "savings", 8900.75, "frozen", "locked", "blocked", "expired", "2026-01-15"),
            ("ACC004", "C003", "savings", 67500.00, "active", "active", "active", "pending", "2026-08-15"),
        ],
    )

    await db.executemany(
        "INSERT INTO cards (card_id, customer_id, account_id, card_type, card_network, last_four, status, blocked_reason, blocked_at, block_ref, expiry) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("CARD001", "C001", "ACC001", "debit", "Visa", "4521", "active", None, None, None, "12/2027"),
            ("CARD002", "C001", "ACC001", "credit", "Mastercard", "8834", "blocked", "lost", "2026-05-10T10:00:00Z", "BLK-20260510-001", "06/2028"),
            ("CARD003", "C002", "ACC003", "debit", "RuPay", "1122", "active", None, None, None, "03/2027"),
            ("CARD004", "C002", "ACC003", "credit", "Visa", "9090", "active", None, None, None, "09/2028"),
            ("CARD005", "C003", "ACC004", "debit", "Mastercard", "3344", "active", None, None, None, "11/2027"),
            ("CARD006", "C003", "ACC004", "credit", "RuPay", "5566", "expired", None, None, None, "01/2026"),
        ],
    )

    await db.executemany(
        "INSERT INTO cheques (cheque_id, account_id, cheque_number, amount, payee, status, stopped_at, stop_ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("CHQ001", "ACC001", "000123", 15000.00, "Acme Corp", "issued", None, None),
            ("CHQ002", "ACC001", "000124", 8500.00, "Rent Payment", "cleared", None, None),
            ("CHQ003", "ACC002", "000456", 25000.00, "Supplier Ltd", "issued", None, None),
            ("CHQ004", "ACC004", "000789", 5000.00, "Utility Bill", "stopped", "2026-06-01T09:00:00Z", "STP-20260601-001"),
        ],
    )

    await db.executemany(
        "INSERT INTO transactions (txn_id, account_id, amount, txn_type, description, status) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("TXN001", "ACC001", 2500.00, "debit", "ATM Withdrawal", "completed"),
            ("TXN002", "ACC001", 45000.00, "credit", "Salary Credit", "completed"),
            ("TXN003", "ACC001", 1200.00, "debit", "Online Shopping", "completed"),
            ("TXN004", "ACC002", 15000.00, "debit", "NEFT Transfer", "completed"),
            ("TXN005", "ACC002", 75000.00, "credit", "Client Payment", "completed"),
            ("TXN006", "ACC003", 500.00, "debit", "UPI Payment", "completed"),
            ("TXN007", "ACC003", 10000.00, "credit", "Fund Transfer", "completed"),
            ("TXN008", "ACC004", 3200.00, "debit", "Bill Payment", "completed"),
            ("TXN009", "ACC004", 50000.00, "credit", "Salary Credit", "completed"),
            ("TXN010", "ACC001", 999.00, "debit", "Subscription", "failed"),
        ],
    )

    await db.commit()
