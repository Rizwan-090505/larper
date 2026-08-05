import asyncio
import datetime
from src.ingestion.db.connection import get_connection
from src.ingestion.db.sync_log import log_sync_event


sync_trigger = asyncio.Event()


async def sync_worker() -> None:
    """Local-only sync worker: mark pending items as synced locally.

    External integrations (Todoist / Google Calendar) have been removed
    — this worker updates local DB sync metadata so the database remains
    coherent and reflected as "synced".
    """
    print("--> [SYNC] Local sync worker started (no external providers)")
    while True:
        try:
            async with get_connection() as conn:
                cursor = await conn.execute(
                    "SELECT t.* FROM tasks t JOIN notes n ON t.note_id = n.id WHERE t.sync_status='pending' AND n.deleted_at IS NULL"
                )
                pending_tasks = await cursor.fetchall()

            if pending_tasks:
                print(f"--> [SYNC] Found {len(pending_tasks)} pending task(s) — marking synced locally")

            for task in pending_tasks:
                try:
                    now = datetime.datetime.utcnow().isoformat()
                    async with get_connection() as conn:
                        await conn.execute(
                            "UPDATE tasks SET sync_status='synced', last_synced_at=? WHERE id=?",
                            (now, task['id']),
                        )
                        await conn.commit()

                    await log_sync_event(
                        event_type='local_sync',
                        entity_type='task',
                        entity_id=task['id'],
                        file_path='',
                        status='synced',
                    )
                except Exception as e:
                    print(f"--> [ERROR] Failed to mark task {task['id']} as synced: {e}")

        except Exception as e:
            print(f"--> [ERROR] Sync worker error: {e}")

        try:
            await asyncio.wait_for(sync_trigger.wait(), timeout=60.0)
            sync_trigger.clear()
        except asyncio.TimeoutError:
            pass


def trigger_sync() -> None:
    """Signal the sync worker to run immediately (useful after DB writes)."""
    try:
        sync_trigger.set()
    except Exception:
        pass