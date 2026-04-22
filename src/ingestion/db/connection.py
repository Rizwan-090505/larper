import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path

from config import settings


@asynccontextmanager
async def get_connection():
    """Context manager for database connections with WAL mode and foreign keys enabled."""
    raw_path = str(settings.DB_PATH).strip("\"'")

    db_path = Path(raw_path)
    if not db_path.is_absolute():
        active_folder = Path(settings.ACTIVE_FOLDER).resolve()
        db_path = active_folder / db_path
    else:
        db_path = db_path.resolve()

    print(f"--> [DB] Opening database at: {db_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = await aiosqlite.connect(str(db_path))
    try:
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        conn.row_factory = aiosqlite.Row
        yield conn
    finally:
        await conn.close()
