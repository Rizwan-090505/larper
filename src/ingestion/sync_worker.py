import asyncio
import datetime
from src.ingestion.db import get_connection, log_sync_event
from src.ingestion.sync import todolist_client


sync_trigger = asyncio.Event()

async def sync_worker() -> None:
    """Syncs pending tasks to ToDoList."""
    print("--> [SYNC] Sync worker started")
    backoff = 5  # seconds, initial backoff
    max_backoff = 300  # seconds
    while True:
        try:
            async with get_connection() as conn:
                cursor = await conn.execute(
                    "SELECT t.* FROM tasks t JOIN notes n ON t.note_id = n.id WHERE t.sync_status='pending' AND n.deleted_at IS NULL"
                )
                pending_tasks = await cursor.fetchall()

            if pending_tasks:
                print(f"--> [SYNC] Found {len(pending_tasks)} pending task(s) to sync")

            for task in pending_tasks:
                try:
                    if task['is_deleted'] == 1:
                        if task['todolist_id']:
                            await todolist_client.delete_task(task['todolist_id'])
                            await log_sync_event(
                                event_type='delete',
                                entity_type='task',
                                entity_id=task['id'],
                                file_path="",
                                status='synced'
                            )
                        async with get_connection() as conn:
                            await conn.execute("DELETE FROM tasks WHERE id=?", (task['id'],))
                            await conn.commit()
                        print(f"--> [SYNC] Deleted task {task['id']} from ToDoList and local DB")
                        continue

                    if not task['todolist_id']:
                        todolist_task = await todolist_client.create_task(
                            content=task['title'],
                            due_date=task['due_date']
                        )
                        todolist_id = str(todolist_task['id'])
                        action = 'create'
                    else:
                        updates = {'content': task['title']}
                        if task['due_date']:
                            updates['due_date'] = task['due_date']
                        await todolist_client.update_task(task['todolist_id'], updates)
                        todolist_id = task['todolist_id']
                        action = 'update'

                    now = datetime.datetime.utcnow().isoformat()
                    async with get_connection() as conn:
                        await conn.execute("""
                            UPDATE tasks SET todolist_id=?, sync_status='synced', last_synced_at=?
                            WHERE id=?
                        """, (todolist_id, now, task['id']))
                        await conn.commit()

                    await log_sync_event(
                        event_type=action,
                        entity_type='task',
                        entity_id=task['id'],
                        file_path="",
                        status='synced'
                    )

                    print(f"--> [SYNC] {action.upper()} task {task['id']} ('{task['title']}') to ToDoList")

                except Exception as e:
                    print(f"--> [ERROR] Failed to sync task {task['id']}: {e}")
                    await log_sync_event(
                        event_type='sync',
                        entity_type='task',
                        entity_id=task['id'],
                        file_path="",
                        status='failed',
                        error_msg=str(e)
                    )
                    # Mark for retry by setting sync_status back to 'pending' (or keep as 'failed' for manual intervention)
                    async with get_connection() as conn:
                        await conn.execute("""
                            UPDATE tasks SET sync_status='failed' WHERE id=?
                        """, (task['id'],))
                        await conn.commit()

            # Reset backoff on success
            backoff = 5

        except Exception as e:
            print(f"--> [ERROR] Sync worker error: {e}")
            print(f"--> [SYNC] Backing off for {backoff} seconds before retrying...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
            continue

        try:
            await asyncio.wait_for(sync_trigger.wait(), timeout=60.0)
            sync_trigger.clear()
        except asyncio.TimeoutError:
            pass