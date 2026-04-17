from src.core.queue import event_queue
from src.core.events import FileEvent
from .processor import process_event


async def ingestion_worker() -> None:
    while True:
        event: FileEvent = await event_queue.get()
        try:
            await process_event(event)
        finally:
            event_queue.task_done()
