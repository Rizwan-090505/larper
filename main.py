import asyncio
import sys
from pathlib import Path

# Add src/TUI to sys.path to allow its local imports to work
tui_path = Path(__file__).parent / "src" / "TUI"
if str(tui_path) not in sys.path:
    sys.path.insert(0, str(tui_path))

from src.ingestion.db import init_db
from src.core.watchdog import start_watchdog
from src.ingestion.parser import parser_worker
from src.ingestion.sync_worker import sync_worker
from src.rag import _preload_vector_db
from src.TUI.app import DevWorkspaceApp

async def async_main():
    # 1. Initialize DB
    await init_db()

    # 2. Start background workers
    watchdog_task = asyncio.create_task(start_watchdog())
    parser_task = asyncio.create_task(parser_worker())
    sync_task = asyncio.create_task(sync_worker())

    # 3. Kick off model weight loading in the background — the TUI shows up
    #    immediately; the embedding model is ready by the time the user first
    #    triggers a RAG call.
    preload_task = asyncio.create_task(_preload_vector_db())

    # 4. Create and run TUI app
    app = DevWorkspaceApp()

    try:
        await app.run_async()
    finally:
        # cleanup
        watchdog_task.cancel()
        parser_task.cancel()
        sync_task.cancel()
        preload_task.cancel()

        # Suppress CancelledError on exit
        for t in [watchdog_task, parser_task, sync_task, preload_task]:
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"Error during shutdown: {e}")

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
