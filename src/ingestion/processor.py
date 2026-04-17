import asyncio
from pathlib import Path
from src.core.events import FileEvent, ParseEvent
from src.core.queue import parser_queue

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
    """Handles 'deleted' file events (Mocked DB)."""
    print(f"\n{'='*50}")
    print(f"🛠️  MOCK DB ACTION: DELETE NOTE")
    print(f"File Path: {path}")
    print(f"Action: Would set deleted_at = UTC now and cascade delete blocks/tasks.")
    print(f"{'='*50}\n")

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
