"""Reset banking.db back to fresh seeded test data.

Usage (from the backend/ directory):
    python reset_db.py

Safe to run while the server is up (SQLite WAL); new conversations get fresh data.
"""
import asyncio

from config import get_settings
from database.connection import init_db, get_db, close_db
from database.seed import seed_database

# Delete child tables before parents (foreign-key safe).
TABLES = ["disputes", "loans", "bills", "transactions", "cheques", "cards", "accounts", "customers"]


async def main() -> None:
    settings = get_settings()
    await init_db(settings.DATABASE_PATH)
    db = await get_db()
    for table in TABLES:
        await db.execute(f"DELETE FROM {table}")
    await db.commit()
    await seed_database(db)
    cur = await db.execute("SELECT COUNT(*) FROM customers")
    (n,) = await cur.fetchone()
    print(f"Database '{settings.DATABASE_PATH}' reset to fresh seed data ({n} customers).")
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
