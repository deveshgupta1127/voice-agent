import aiosqlite
from pathlib import Path

_db: aiosqlite.Connection | None = None


async def init_db(db_path: str) -> aiosqlite.Connection:
    global _db
    _db = await aiosqlite.connect(db_path)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")

    schema_path = Path(__file__).parent / "schema.sql"
    schema_sql = schema_path.read_text()
    await _db.executescript(schema_sql)
    await _db.commit()

    cursor = await _db.execute("SELECT COUNT(*) FROM customers")
    row = await cursor.fetchone()
    if row[0] == 0:
        from .seed import seed_database
        await seed_database(_db)

    return _db


async def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None
