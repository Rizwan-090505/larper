"""
Database package — re-exports from sub-modules.

All existing `from src.ingestion.db import X` imports remain valid.
"""

from src.ingestion.db.connection import get_connection
from src.ingestion.db.schema import init_db
from src.ingestion.db.notes import upsert_note, delete_note
from src.ingestion.db.blocks import insert_blocks, insert_references
from src.ingestion.db.tasks import insert_tasks
from src.ingestion.db.sync_log import log_sync_event
from src.ingestion.db.tags import insert_block_tags

__all__ = [
    'get_connection',
    'init_db',
    'upsert_note',
    'delete_note',
    'insert_blocks',
    'insert_references',
    'insert_tasks',
    'log_sync_event',
    'insert_block_tags',
]
