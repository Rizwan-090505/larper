import asyncio
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from src.core.queue import event_queue
from src.core.events import FileEvent
from config import settings


class LARPEREventHandler(FileSystemEventHandler):
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop

    def _should_track(self, path: Path) -> bool:
        return any(part in {"pages", "journals"} for part in path.parts)

    def _enqueue(self, path: Path, event_type: str) -> None:
        if not self._should_track(path):
            return

        event = FileEvent(path=path, event_type=event_type)

        asyncio.run_coroutine_threadsafe(
            event_queue.put(event),
            self.loop,
        )

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._enqueue(Path(event.src_path), "created")

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._enqueue(Path(event.src_path), "modified")

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._enqueue(Path(event.src_path), "deleted")


async def start_watchdog() -> None:
    loop = asyncio.get_running_loop()

    base_path = Path(settings.ACTIVE_FOLDER)

    watch_paths = [
        base_path / "pages",
        base_path / "journals",
    ]

    observer = Observer()
    handler = LARPEREventHandler(loop)

    for path in watch_paths:
        if path.exists():
            observer.schedule(handler, str(path), recursive=True)

    observer.start()

    try:
        while True:
            await asyncio.sleep(1)
    finally:
        observer.stop()
        observer.join()
