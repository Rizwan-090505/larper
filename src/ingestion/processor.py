import asyncio
from pathlib import Path
from src.core.events import FileEvent, ParseEvent
from src.core.queue import parser_queue
from src.ingestion.db import delete_note, get_block_ids_for_note, get_connection

# NOTE: src.rag.vector_db is intentionally NOT imported at the top level.
# Importing it eagerly pulls in faiss + sentence-transformers on the main thread
# at startup, which blocks the TUI from rendering. _get_vector_db() is imported
# lazily inside _handle_deletion(), which only runs once a real delete event fires.

async def process_event(event: FileEvent) -> None:
    """
    Main entry point for processing filesystem events dequeued by the worker.
    """
    path = Path(event.path)
    
    # Route logic based on event type
    if event.event_type == 'deleted':
        await _handle_deletion(path)
    elif event.event_type in ('created', 'modified'):
        await _handle_upsert(path, event.event_type)
    else:
        print(f"--> [WARNING] Unknown event type: {event.event_type}")

async def _handle_deletion(path: Path) -> None:
    """Handles 'deleted' file events.

    Lifecycle:
      1. Fetch old block_ids from SQLite (before they're gone).
      2. Remove stale embeddings from the Vector DB.
      3. Soft-delete the note (sets deleted_at; blocks are left for FK integrity
         but are no longer reachable via the RAG index).
    """
    abs_path = str(path.resolve())

    # Step 1 – find the note_id so we can look up its blocks
    async with get_connection() as conn:
        cursor = await conn.execute(
            "SELECT id FROM notes WHERE file_path=? AND deleted_at IS NULL",
            (abs_path,),
        )
        row = await cursor.fetchone()

    if row:
        note_id = row["id"]

        # Step 2 – fetch old block IDs before any deletion touches them
        old_block_ids = await get_block_ids_for_note(note_id)

        # Step 3 – purge stale embeddings from FAISS
        if old_block_ids:
            from src.rag.vector_db import _get_vector_db  # deferred: avoids NLP import at startup
            vector_db = _get_vector_db()
            vector_db.remove_by_block_ids(old_block_ids)
            print(f"--> [VectorDB] Removed {len(old_block_ids)} embeddings for deleted note {note_id}")

    # Step 4 – soft-delete the note in SQLite
    await delete_note(path)
    print(f"Note deleted: {path}")

async def _handle_upsert(path: Path, event_type: str) -> None:
    """Handles 'created' and 'modified' file events (Mocked DB)."""
    try:
        # 1. Read file content
        try:
            raw_content = path.read_text(encoding='utf-8')
        except FileNotFoundError:
            print(f"--> [WARNING] File {path} deleted before we could read it.")
            return await _handle_deletion(path)

        # 2. Determine Note Type based on directory structure
        note_type = "journal" if "journals" in path.parts else "page"
        
        # 3. Enqueue to parser queue
        parse_event = ParseEvent(
            path=path,
            raw_content=raw_content,
            note_type=note_type,
            event_type=event_type
        )
        await parser_queue.put(parse_event)

    except Exception as e:
        print(f"--> [ERROR] Failed processing {path}: {str(e)}")
