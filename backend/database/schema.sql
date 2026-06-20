CREATE TABLE IF NOT EXISTS customers (
    customer_id     TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    mobile          TEXT NOT NULL UNIQUE,
    dob             TEXT NOT NULL,
    email           TEXT,
    language_pref   TEXT DEFAULT 'hi-IN',
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id          TEXT PRIMARY KEY,
    customer_id         TEXT NOT NULL REFERENCES customers(customer_id),
    account_type        TEXT NOT NULL,
    balance             REAL NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'active',
    netbanking_status   TEXT DEFAULT 'active',
    debit_card_pin      TEXT DEFAULT 'active',
    kyc_status          TEXT DEFAULT 'verified',
    kyc_expiry          TEXT,
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cards (
    card_id         TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES customers(customer_id),
    account_id      TEXT REFERENCES accounts(account_id),
    card_type       TEXT NOT NULL,
    card_network    TEXT NOT NULL,
    last_four       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',
    blocked_reason  TEXT,
    blocked_at      TEXT,
    block_ref       TEXT,
    expiry          TEXT NOT NULL,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cheques (
    cheque_id       TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES accounts(account_id),
    cheque_number   TEXT NOT NULL,
    amount          REAL,
    payee           TEXT,
    status          TEXT NOT NULL DEFAULT 'issued',
    stopped_at      TEXT,
    stop_ref        TEXT,
    issued_at       TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    txn_id          TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES accounts(account_id),
    amount          REAL NOT NULL,
    txn_type        TEXT NOT NULL,
    description     TEXT,
    status          TEXT DEFAULT 'completed',
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bills (
    bill_id         TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES accounts(account_id),
    biller_name     TEXT NOT NULL,
    biller_id       TEXT NOT NULL,
    bill_type       TEXT NOT NULL,
    amount          REAL NOT NULL,
    due_date        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    paid_at         TEXT,
    payment_ref     TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS loans (
    loan_id         TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES accounts(account_id),
    loan_type       TEXT NOT NULL,
    principal       REAL NOT NULL,
    outstanding     REAL NOT NULL,
    emi_amount      REAL NOT NULL,
    interest_rate   REAL NOT NULL,
    tenure_months   INTEGER NOT NULL,
    next_due_date   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS disputes (
    dispute_id      TEXT PRIMARY KEY,
    txn_id          TEXT NOT NULL REFERENCES transactions(txn_id),
    account_id      TEXT NOT NULL REFERENCES accounts(account_id),
    reason          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open',
    reference       TEXT NOT NULL,
    raised_at       TEXT DEFAULT CURRENT_TIMESTAMP,
    resolved_at     TEXT
);
