import datetime
from typing import Optional

from src.ingestion.db.connection import get_connection


async def log_sync_event(event_type: str, entity_type: str, file_path: str,
                         status: str, entity_id: Optional[int] = None,
                         error_msg: Optional[str] = None) -> None:
    """Log a sync event to the sync_log table."""
    now = datetime.datetime.utcnow().isoformat()
    async with get_connection() as conn:
        await conn.execute("""
            INSERT INTO sync_log
                (event_type, entity_type, entity_id, file_path, status, error_msg, logged_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (event_type, entity_type, entity_id, str(file_path), status, error_msg, now))
        await conn.commit()
        print(f"--> [DB] Logged sync event: {event_type}/{entity_type} -> {status}")
