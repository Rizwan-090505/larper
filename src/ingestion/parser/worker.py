from typing import List, Dict, Any
import logging

from src.core.queue import parser_queue
from src.core.events import ParseEvent
from src.ingestion.db import (
    upsert_note,
    insert_blocks,
    insert_tasks,
    insert_references,
    insert_block_tags,
    get_connection,
    delete_note,
    get_block_ids_for_note,
)
from src.ingestion.sync_worker import sync_trigger
from src.ingestion.parser.core import parse_markdown
# DEFERRED IMPORT: Heavy NLP modules (sentence-transformers + faiss) are imported
# inside parser_worker() to avoid blocking startup. This saves 1-2 seconds.


async def _resolve_references(references: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    resolved = []

    async with get_connection() as conn:
        cursor = await conn.execute(
            "SELECT id, title FROM notes WHERE deleted_at IS NULL"
        )
        notes = await cursor.fetchall()
        title_to_id = {n["title"]: n["id"] for n in notes}

        for ref in references:
            target_title = ref["target_title"]
            target_block = ref.get("target_block")

            target_note_id = title_to_id.get(target_title)
            if not target_note_id:
                continue

            target_block_id = None

            if target_block:
                cursor = await conn.execute(
                    "SELECT id FROM blocks WHERE note_id=? AND content LIKE ?",
                    (target_note_id, f"%{target_block}%"),
                )
                block_row = await cursor.fetchone()
                if block_row:
                    target_block_id = block_row["id"]

            resolved.append(
                {
                    "source_block_id": ref["source_block_id"],
                    "target_note_id": target_note_id,
                    "target_block_id": target_block_id,
                    "target_title": target_title,
                    "reference_type": ref.get("reference_type", "link"),
                }
            )

    return resolved


async def parser_worker() -> None:
    logging.basicConfig(level=logging.INFO)
    
    # IMPORT HEAVY NLP MODULES HERE - deferred to avoid startup cost
    # This happens AFTER the TUI has already started rendering
    from src.rag.vector_db import add_blocks_to_vector_db, _get_vector_db
    
    logging.info("Parser worker starting - loading NLP models...")
    vector_db = _get_vector_db()
    logging.info("Parser worker ready - NLP models loaded")

    while True:
        event = None

        try:
            event: ParseEvent = await parser_queue.get()

            title, blocks, tasks, references, block_tags = parse_markdown(
                event.path, event.raw_content
            )

            note_id = await upsert_note(
                event.path,
                title,
                event.note_type,
                event.raw_content,
                event.event_type,
            )

            # --- Vector DB sync: Step 1 & 2 ---
            # Fetch old block_ids BEFORE insert_blocks deletes them from SQLite,
            # so we can purge their stale embeddings from FAISS.
            old_block_ids = await get_block_ids_for_note(note_id)
            if old_block_ids:
                vector_db.remove_by_block_ids(old_block_ids)
                logging.info(
                    f"Removed {len(old_block_ids)} stale embeddings for note {note_id}"
                )

            # --- SQLite transaction: Step 3 ---
            # insert_blocks deletes the old rows and inserts fresh ones atomically.
            block_ids = await insert_blocks(note_id, blocks)

            # Remap parser-local block indices (0, 1, 2…) → real SQLite rowids
            local_to_db = {local_idx: db_id for local_idx, db_id in enumerate(block_ids)}

            for bt in block_tags:
                bt["block_id"] = local_to_db.get(bt["block_id"])

            for task in tasks:
                task["block_id"] = local_to_db.get(task["block_id"])

            for ref in references:
                ref["source_block_id"] = local_to_db.get(ref["source_block_id"])

            await insert_block_tags(block_ids, block_tags)
            await insert_tasks(note_id, tasks)

            if block_ids and blocks:
                contents = [b["content"] for b in blocks]
                await add_blocks_to_vector_db(block_ids, contents)
                logging.info(
                    f"Embeddings added for note {note_id} ({len(block_ids)} blocks)"
                )

            if references:
                resolved_refs = await _resolve_references(references)
                if resolved_refs:
                    await insert_references(note_id, resolved_refs)

            sync_trigger.set()

            logging.info(
                f"Processed {event.event_type}: {event.path} (ID: {note_id})"
            )

        except Exception as e:
            logging.error(f"Parser worker failed: {e}")

        finally:
            if event is not None:
                parser_queue.task_done()