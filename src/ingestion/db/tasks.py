from src.ingestion.db.connection import get_connection


async def insert_tasks(note_id: int, tasks: list) -> None:
    """Insert/update tasks for a note, tracking sync status for changes."""
    async with get_connection() as conn:
        # Null out block_id on ALL existing tasks for this note first —
        # blocks were just re-inserted with new rowids, so any surviving
        # task row still pointing at the old block rowids would violate the FK.
        await conn.execute(
            "UPDATE tasks SET block_id=NULL WHERE note_id=?", (note_id,)
        )

        cursor = await conn.execute(
            "SELECT * FROM tasks WHERE note_id=? AND is_deleted=0", (note_id,)
        )
        existing_tasks = await cursor.fetchall()
        existing_map = {row['title']: row for row in existing_tasks}

        new_titles = set()
        updated_count = 0
        inserted_count = 0

        for task in tasks:
            title = task['title']
            new_titles.add(title)

            if title in existing_map:
                old = existing_map[title]
                needs_sync = (
                    old['is_done'] != task['is_done']
                    or old['due_date'] != task['due_date']
                    or old['raw_text'] != task['raw_text']
                )
                sync_status = 'pending' if needs_sync else old['sync_status']

                await conn.execute("""
                    UPDATE tasks
                    SET block_id=?, raw_text=?, is_done=?, due_date=?,
                        priority=?, tags=?, recurrence=?, start_date=?,
                        sync_status=?
                    WHERE id=?
                """, (
                    task['block_id'], task['raw_text'], task['is_done'],
                    task['due_date'], task.get('priority'),
                    task.get('tags'), task.get('recurrence'),
                    task.get('start_date'), sync_status, old['id'],
                ))
                updated_count += 1
            else:
                await conn.execute("""
                    INSERT INTO tasks
                        (note_id, block_id, raw_text, title, is_done, due_date,
                         priority, tags, recurrence, start_date, sync_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """, (
                    note_id, task['block_id'], task['raw_text'], title,
                    task['is_done'], task['due_date'], task.get('priority'),
                    task.get('tags'), task.get('recurrence'),
                    task.get('start_date'),
                ))
                inserted_count += 1

        # Mark tasks not in new list as deleted
        deleted_count = 0
        for title, row in existing_map.items():
            if title not in new_titles:
                await conn.execute("""
                    UPDATE tasks SET is_deleted=1, sync_status='pending' WHERE id=?
                """, (row['id'],))
                deleted_count += 1

        await conn.commit()
        print(f"--> [DB] Tasks for note {note_id}: "
              f"inserted={inserted_count}, updated={updated_count}, deleted={deleted_count}")
