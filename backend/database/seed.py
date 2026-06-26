import aiosqlite


async def seed_database(db: aiosqlite.Connection) -> None:
    await db.executemany(
        "INSERT INTO customers (customer_id, name, mobile, dob, email, language_pref) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("C001", "Rahul Sharma", "9876543210", "15-08-1990", "rahul@example.com", "hi-IN"),
            ("C002", "Priya Patel", "9123456789", "22-03-1985", "priya@example.com", "en-IN"),
            ("C003", "Amit Verma", "9988776655", "10-12-1995", "amit@example.com", "hi-IN"),
            # ── Added test personas (C004–C008) for edge-case scenarios ──
            ("C004", "Sneha Reddy", "9870011223", "05-05-1992", "sneha@example.com", "en-IN"),
            ("C005", "Vikram Singh", "9865432109", "28-11-1988", "vikram@example.com", "hi-IN"),
            ("C006", "Anjali Nair", "9854321098", "12-07-1991", "anjali@example.com", "en-IN"),
            ("C007", "Mohammed Khan", "9843210987", "19-02-1983", "mohammed@example.com", "hi-IN"),
            ("C008", "Deepa Iyer", "9832109876", "30-09-1996", "deepa@example.com", "en-IN"),
        ],
    )

    await db.executemany(
        "INSERT INTO accounts (account_id, customer_id, account_type, balance, status, netbanking_status, debit_card_pin, kyc_status, kyc_expiry) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("ACC001", "C001", "savings", 45230.50, "active", "active", "active", "verified", "2027-08-15"),
            ("ACC002", "C001", "current", 125000.00, "active", "active", "active", "verified", "2027-08-15"),
            ("ACC003", "C002", "savings", 8900.75, "frozen", "locked", "blocked", "expired", "2026-01-15"),
            ("ACC004", "C003", "savings", 67500.00, "active", "active", "active", "pending", "2026-08-15"),
            # C004 — low balance: can pay the small water bill, not the big electricity bill.
            ("ACC005", "C004", "savings", 350.00, "active", "active", "active", "verified", "2027-05-05"),
            # C005 — healthy current account, used for cheque + dispute edge cases.
            ("ACC006", "C005", "current", 95000.00, "active", "active", "active", "verified", "2027-11-28"),
            # C006 — two healthy accounts, multiple loans and bills (happy path / multi-task).
            ("ACC007", "C006", "savings", 220000.00, "active", "active", "active", "verified", "2028-07-12"),
            ("ACC008", "C006", "current", 540000.00, "active", "active", "active", "verified", "2028-07-12"),
            # C007 — everything wrong: frozen, netbanking locked, PIN blocked, KYC expired.
            ("ACC009", "C007", "savings", 15600.00, "frozen", "locked", "blocked", "expired", "2026-02-19"),
            # C008 — clean single account, no bills, no loans (empty-state handling).
            ("ACC010", "C008", "savings", 12000.00, "active", "active", "active", "verified", "2028-09-30"),
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
            # C004 — one active debit to block, one already-blocked credit (block-again edge case).
            ("CARD007", "C004", "ACC005", "debit", "Visa", "7788", "active", None, None, None, "10/2027"),
            ("CARD008", "C004", "ACC005", "credit", "RuPay", "9911", "blocked", "stolen", "2026-06-01T08:30:00Z", "BLK-20260601-007", "07/2028"),
            ("CARD009", "C005", "ACC006", "debit", "Mastercard", "2233", "active", None, None, None, "04/2028"),
            ("CARD010", "C006", "ACC007", "debit", "Visa", "4455", "active", None, None, None, "08/2028"),
            ("CARD011", "C006", "ACC008", "credit", "Visa", "6677", "active", None, None, None, "08/2029"),
            ("CARD012", "C007", "ACC009", "debit", "RuPay", "8899", "active", None, None, None, "02/2027"),
            ("CARD013", "C008", "ACC010", "debit", "Mastercard", "1010", "active", None, None, None, "09/2028"),
        ],
    )

    await db.executemany(
        "INSERT INTO cheques (cheque_id, account_id, cheque_number, amount, payee, status, stopped_at, stop_ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("CHQ001", "ACC001", "000123", 15000.00, "Acme Corp", "issued", None, None),
            ("CHQ002", "ACC001", "000124", 8500.00, "Rent Payment", "cleared", None, None),
            ("CHQ003", "ACC002", "000456", 25000.00, "Supplier Ltd", "issued", None, None),
            ("CHQ004", "ACC004", "000789", 5000.00, "Utility Bill", "stopped", "2026-06-01T09:00:00Z", "STP-20260601-001"),
            # C005 — one stoppable cheque, one already cleared (stop-fails edge case).
            ("CHQ005", "ACC006", "000555", 30000.00, "Wholesale Traders", "issued", None, None),
            ("CHQ006", "ACC006", "000556", 12000.00, "Vendor Payment", "cleared", None, None),
            # C006 — a stoppable cheque on the savings account.
            ("CHQ007", "ACC007", "000777", 45000.00, "Builder Advance", "issued", None, None),
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
            # C004 — small spends.
            ("TXN011", "ACC005", 1500.00, "debit", "Grocery Store", "completed"),
            ("TXN012", "ACC005", 2000.00, "credit", "Refund", "completed"),
            # C005 — TXN015 already has an open dispute (raise-again edge case).
            ("TXN013", "ACC006", 8000.00, "debit", "Equipment Purchase", "completed"),
            ("TXN014", "ACC006", 60000.00, "credit", "Invoice Payment", "completed"),
            ("TXN015", "ACC006", 4500.00, "debit", "Unknown Online Charge", "completed"),
            # C006 — credits on both accounts.
            ("TXN016", "ACC007", 25000.00, "credit", "Salary Credit", "completed"),
            ("TXN017", "ACC008", 100000.00, "credit", "Client Payment", "completed"),
            ("TXN018", "ACC007", 7800.00, "debit", "Furniture Purchase", "failed"),
            # C008 — single small spend.
            ("TXN019", "ACC010", 500.00, "debit", "Mobile Recharge", "completed"),
        ],
    )

    await db.executemany(
        "INSERT INTO bills (bill_id, account_id, biller_name, biller_id, bill_type, amount, due_date, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("BILL001", "ACC001", "Tata Power", "BP001", "electricity", 2150.00, "2026-07-15", "pending"),
            ("BILL002", "ACC001", "Municipal Water", "BP002", "water", 850.00, "2026-07-20", "pending"),
            ("BILL003", "ACC002", "HDFC Life Insurance", "BP003", "insurance", 12500.00, "2026-07-05", "pending"),
            ("BILL004", "ACC004", "Mahanagar Gas", "BP004", "gas", 1800.00, "2026-07-10", "pending"),
            ("BILL005", "ACC004", "Adani Electricity", "BP005", "electricity", 3200.00, "2026-06-15", "overdue"),
            ("BILL006", "ACC001", "Home Loan EMI", "BP006", "emi", 18500.00, "2026-07-05", "pending"),
            # C004 — big bill (₹3200) exceeds ₹350 balance → insufficient funds; small bill (₹300) is payable.
            ("BILL007", "ACC005", "Reliance Energy", "BP007", "electricity", 3200.00, "2026-07-12", "pending"),
            ("BILL008", "ACC005", "City Water Board", "BP008", "water", 300.00, "2026-07-18", "pending"),
            # C006 — bills on both accounts (one overdue).
            ("BILL009", "ACC007", "BSES Rajdhani", "BP009", "electricity", 4100.00, "2026-07-08", "pending"),
            ("BILL010", "ACC008", "LIC Premium", "BP010", "insurance", 22000.00, "2026-06-20", "overdue"),
            # C007 — a pending bill, but the account is frozen → payment refused.
            ("BILL011", "ACC009", "Indane Gas", "BP011", "gas", 1100.00, "2026-07-14", "pending"),
        ],
    )

    await db.executemany(
        "INSERT INTO loans (loan_id, account_id, loan_type, principal, outstanding, emi_amount, interest_rate, tenure_months, next_due_date, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("LOAN001", "ACC001", "home", 2500000.00, 1850000.00, 18500.00, 8.5, 240, "2026-07-05", "active"),
            ("LOAN002", "ACC004", "personal", 500000.00, 320000.00, 12800.00, 11.0, 48, "2026-07-10", "active"),
            # C005 — a personal loan.
            ("LOAN003", "ACC006", "personal", 300000.00, 150000.00, 9800.00, 12.5, 36, "2026-07-20", "active"),
            # C006 — two loans across the two accounts (car + education).
            ("LOAN004", "ACC007", "car", 800000.00, 450000.00, 15200.00, 9.5, 60, "2026-07-08", "active"),
            ("LOAN005", "ACC008", "education", 1200000.00, 980000.00, 14500.00, 8.0, 84, "2026-07-15", "active"),
        ],
    )

    await db.executemany(
        "INSERT INTO disputes (dispute_id, txn_id, account_id, reason, status, reference) VALUES (?, ?, ?, ?, ?, ?)",
        [
            # Pre-existing open dispute on C005's TXN015 — raising another must be refused.
            ("D5001", "TXN015", "ACC006", "unauthorized_charge", "open", "DSP-20260605-501"),
        ],
    )

    await db.commit()
