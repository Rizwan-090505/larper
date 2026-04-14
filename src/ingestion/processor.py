from src.core.events import FileEvent


async def process_event(event: FileEvent) -> None:
    # TODO: implement parsing, embedding, DB sync etc.
    print(f"[INGEST] {event.event_type}: {event.path}")
