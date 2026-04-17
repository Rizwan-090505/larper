import aiosqlite
from contextlib import asynccontextmanager
import os
from pathlib import Path

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
                todoist_id TEXT NULLABLE UNIQUE,
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
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_todoist_id ON tasks(todoist_id);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_sync_log_logged_at ON sync_log(logged_at);")
        await conn.commit()
