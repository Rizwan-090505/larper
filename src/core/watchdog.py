import asyncio
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from src.core.queue import event_queue
from src.core.events import FileEvent
from config import settings


class LARPEREventHandler(FileSystemEventHandler):
    def __init__(self, loop: asyncio.AbstractEventLoop, watch_paths: list[Path]):
        self.loop = loop
        # FIX Bug 3: Store the resolved watch roots so _should_track checks
        # against the actual watched directories, not just any folder named
        # "pages" or "journals" anywhere in the absolute path.
        self.watch_roots = {p.resolve() for p in watch_paths}

    def _should_track(self, path: Path) -> bool:
        resolved = path.resolve()
        return any(
            resolved == root or root in resolved.parents
            for root in self.watch_roots
        )

    def _enqueue(self, path: Path, event_type: str) -> None:
        print(f"[WATCHDOG EVENT] {event_type} → {path}")  # Debug log for visibility
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


# FIX Bug 1: This is now a self-contained async function that manages the
# observer lifecycle internally. main.py runs it as a task via
# asyncio.create_task(), not as a regular function call expecting a return value.
async def start_watchdog() -> None:
    loop = asyncio.get_running_loop()

    base_path = Path(settings.ACTIVE_FOLDER).resolve()

    watch_paths = [
        base_path / "pages",
        base_path / "journals",
    ]

    # FIX Bug 2: Always create the watch directories before scheduling.
    # Previously, non-existent paths were silently skipped, meaning no events
    # would ever fire for them.
    for path in watch_paths:
        path.mkdir(parents=True, exist_ok=True)

    observer = Observer()
    handler = LARPEREventHandler(loop, watch_paths)

    for path in watch_paths:
        observer.schedule(handler, str(path), recursive=True)

    observer.start()
    print(f"Watchdog started. Monitoring: {[str(p) for p in watch_paths]}")

    try:
        while True:
            await asyncio.sleep(1)
    finally:
        observer.stop()
        observer.join()
        print("Watchdog stopped.")
