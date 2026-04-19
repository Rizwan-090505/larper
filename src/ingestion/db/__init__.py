import aiosqlite
from contextlib import asynccontextmanager
import os
from pathlib import Path
import datetime

# Import settings
from config import settings

@asynccontextmanager
async def get_connection():
    # 1. Grab the path and clean it up (strips accidental quotes from .env)
    raw_path = str(settings.DB_PATH).strip("\"'")
    
    # 2. Force it to be an absolute path
    db_path = Path(raw_path).resolve()
    
    # 3. Print it out so we can see exactly where it's going
    print(f"--> [DEBUG] Opening database at: {db_path}")
    
    # 4. Guarantee the parent folder actually exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # 5. Connect!
    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        conn.row_factory = aiosqlite.Row
        yield conn
    finally:
        await conn.close()

async def init_db() -> None:
    async with get_connection() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                note_type TEXT NOT NULL,
                raw_content TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                deleted_at DATETIME NULLABLE
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id INTEGER,
                block_type TEXT NOT NULL,
                content TEXT NOT NULL,
                level INTEGER NULLABLE,
                position INTEGER NOT NULL,
                parent_block INTEGER NULLABLE,
                FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE,
                FOREIGN KEY (parent_block) REFERENCES blocks(id) ON DELETE CASCADE
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id INTEGER,
                block_id INTEGER,
                raw_text TEXT NOT NULL,
                title TEXT NOT NULL,
                is_done INTEGER DEFAULT 0,
                due_date TEXT NULLABLE,
                todolist_id TEXT NULLABLE UNIQUE,
                gcal_event_id TEXT NULLABLE,
                sync_status TEXT DEFAULT 'pending',
                last_synced_at DATETIME NULLABLE,
                FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE,
                FOREIGN KEY (block_id) REFERENCES blocks(id) ON DELETE CASCADE
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id INTEGER NULLABLE,
                file_path TEXT NOT NULL,
                status TEXT NOT NULL,
                error_msg TEXT NULLABLE,
                logged_at DATETIME NOT NULL
            )
        """)
        
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_file_path ON notes(file_path);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_note_id ON tasks(note_id);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_todolist_id ON tasks(todolist_id);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_sync_log_logged_at ON sync_log(logged_at);")
        await conn.commit()

#faisal's code for upsert and delete operations, plus block/task insertion logic        


async def upsert_note(file_path: str, title: str, note_type: str, raw_content: str, event_type: str) -> int:
    now = datetime.datetime.utcnow().isoformat()
    async with get_connection() as conn:
        if event_type == 'created':
            cursor = await conn.execute("""
                INSERT INTO notes (file_path, title, note_type, raw_content, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (str(file_path), title, note_type, raw_content, now, now))
            note_id = cursor.lastrowid
        elif event_type == 'modified':
            await conn.execute("""
                UPDATE notes SET title=?, raw_content=?, updated_at=? WHERE file_path=?
            """, (title, raw_content, now, str(file_path)))
            cursor = await conn.execute("SELECT id FROM notes WHERE file_path=?", (str(file_path),))
            row = await cursor.fetchone()
            note_id = row['id']
        await conn.commit()
        return note_id


async def insert_blocks(note_id: int, blocks: list):
    async with get_connection() as conn:
        # Delete existing blocks for the note
        await conn.execute("DELETE FROM blocks WHERE note_id=?", (note_id,))
        for block in blocks:
            await conn.execute("""
                INSERT INTO blocks (note_id, block_type, content, level, position, parent_block)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (note_id, block['block_type'], block['content'], block.get('level'), block['position'], block.get('parent_block')))
        await conn.commit()


async def insert_tasks(note_id: int, tasks: list):
    async with get_connection() as conn:
        # Delete existing tasks for the note
        await conn.execute("DELETE FROM tasks WHERE note_id=?", (note_id,))
        for task in tasks:
            await conn.execute("""
                INSERT INTO tasks (note_id, block_id, raw_text, title, is_done, due_date)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (note_id, task['block_id'], task['raw_text'], task['title'], task['is_done'], task['due_date']))
        await conn.commit()


async def delete_note(file_path: str):
    now = datetime.datetime.utcnow().isoformat()
    async with get_connection() as conn:
        await conn.execute("UPDATE notes SET deleted_at=? WHERE file_path=?", (now, str(file_path)))
        await conn.commit()
