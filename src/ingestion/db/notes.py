import datetime
from pathlib import Path

from src.ingestion.db.connection import get_connection


async def upsert_note(file_path: str, title: str, note_type: str,
                      raw_content: str, event_type: str) -> int:
    """Insert or update a note in the database."""
    now = datetime.datetime.utcnow().isoformat()
    note_id = -1
    # Always use absolute path for DB lookup
    abs_path = str(Path(file_path).resolve())
    try:
        async with get_connection() as conn:
            if event_type == 'created':
                cursor = await conn.execute("""
                    INSERT INTO notes (file_path, title, note_type, raw_content, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (abs_path, title, note_type, raw_content, now, now))
                note_id = cursor.lastrowid
                print(f"--> [DB] Created note: {title} (ID: {note_id})")

            elif event_type == 'modified':
                check = await conn.execute(
                    "SELECT id FROM notes WHERE file_path=?", (abs_path,)
                )
                existing = await check.fetchone()

                if existing:
                    await conn.execute("""
                        UPDATE notes SET title=?, raw_content=?, updated_at=? WHERE file_path=?
                    """, (title, raw_content, now, abs_path))
                    note_id = existing['id']
                    print(f"--> [DB] Updated note: {title} (ID: {note_id})")
                else:
                    cursor = await conn.execute("""
                        INSERT INTO notes (file_path, title, note_type, raw_content, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (abs_path, title, note_type, raw_content, now, now))
                    note_id = cursor.lastrowid
                    print(f"--> [DB] Created note (from modified event): {title} (ID: {note_id})")

            await conn.commit()
    except Exception as e:
        print(f"[ERROR] upsert_note failed for {file_path}: {e}")
        note_id = -1
    return note_id


async def delete_note(file_path: str) -> None:
    """Soft-delete a note by setting deleted_at timestamp."""
    now = datetime.datetime.utcnow().isoformat()
    abs_path = str(Path(file_path).resolve())
    async with get_connection() as conn:
        await conn.execute(
            "UPDATE notes SET deleted_at=? WHERE file_path=?",
            (now, abs_path)
        )
        await conn.commit()
        print(f"--> [DB] Deleted note: {abs_path}")
