import asyncio
from pathlib import Path

from config import settings
from src.ingestion.db import init_db
from src.core.watchdog import start_watchdog
from src.ingestion.worker import ingestion_worker
#faisal
from src.ingestion.sync_worker import sync_worker


async def main():
    print("Initializing LARPER Database Schema...")
    await init_db()
    print(f"Database successfully verified at: {settings.DB_PATH}\n")

    # Ensure the target folder exists
    folder_to_watch = Path(settings.ACTIVE_FOLDER).resolve()
    folder_to_watch.mkdir(parents=True, exist_ok=True)
    print(f"Watching folder: {folder_to_watch}")

    # FIX Bug 1: Run watchdog as a concurrent task instead of calling it
    # as a regular function and expecting an observer return value.
    watchdog_task = asyncio.create_task(start_watchdog())
    worker_task = asyncio.create_task(ingestion_worker())
    
    from src.ingestion.parser import parser_worker
    parser_task = asyncio.create_task(parser_worker())
    #faisal
    sync_task = asyncio.create_task(sync_worker())

    try:
        # Run both tasks concurrently — both run forever until interrupted
        await asyncio.gather(watchdog_task, worker_task, parser_task, sync_task)
    except asyncio.CancelledError:
        pass
    # NOTE: No observer.stop()/join() here — start_watchdog() handles its
    # own cleanup internally in its finally block.


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown signal received. Exiting LARPER gracefully.")
