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
