"""
Parser worker
=============
Consumes ParseEvent items from parser_queue, runs the markdown parser,
writes to SQLite, and generates embeddings (standard + hierarchical) in
background tasks so the TUI is never blocked.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

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
from src.ingestion.parser.core import parse_markdown

log = logging.getLogger(__name__)

# DEFERRED IMPORTS: Heavy NLP modules (sentence-transformers + faiss) are
# imported inside parser_worker() to avoid blocking startup.


# ---------------------------------------------------------------------------
# Reference resolution helper
# ---------------------------------------------------------------------------


async def _resolve_references(
    references: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
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
                row = await cursor.fetchone()
                if row:
                    target_block_id = row["id"]

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


# ---------------------------------------------------------------------------
# Background embedding tasks
# ---------------------------------------------------------------------------


async def _generate_embeddings_async(
    block_ids: List[int],
    contents: List[str],
    note_id: int,
) -> None:
    """Standard FAISS embeddings – runs in background after SQLite commit."""
    try:
        from src.rag.vector_db import add_blocks_to_vector_db

        await add_blocks_to_vector_db(block_ids, contents)
        log.info("Embeddings added for note %d (%d blocks)", note_id, len(block_ids))
    except Exception as exc:
        log.error("Embedding generation failed for note %d: %s", note_id, exc)


async def _generate_hierarchical_embeddings_async(
    block_ids: List[int],
    contents: List[str],
    note_id: int,
    titles: List[str],
    file_paths: List[str],
) -> None:
    """
    Multi-hierarchical FAISS embeddings (doc / paragraph / sentence).
    Runs as a separate background task after the standard embeddings task is
    scheduled so it never slows down task ingestion.
    """
    try:
        from src.rag.multi_hierarchical import get_hierarchical_db

        hier_db = get_hierarchical_db()
        note_ids = [note_id] * len(block_ids)
        await hier_db.add_hierarchical_embeddings(
            block_ids, contents, note_ids, titles, file_paths
        )
        log.info(
            "Hierarchical embeddings added for note %d (%d blocks)",
            note_id,
            len(block_ids),
        )
    except Exception as exc:
        log.error(
            "Hierarchical embedding generation failed for note %d: %s",
            note_id,
            exc,
        )


# ---------------------------------------------------------------------------
# Main worker loop
# ---------------------------------------------------------------------------


async def parser_worker() -> None:
    logging.basicConfig(level=logging.INFO)

    # Deferred heavy import – happens after TUI has rendered
    from src.rag.vector_db import _get_vector_db

    log.info("Parser worker starting – loading NLP models…")
    vector_db = _get_vector_db()
    log.info("Parser worker ready – NLP models loaded")

    while True:
        event: ParseEvent | None = None
        try:
            event = await parser_queue.get()

            # ── Parse ────────────────────────────────────────────────────────
            title, blocks, tasks, references, block_tags = parse_markdown(
                event.path, event.raw_content
            )

            # ── SQLite upsert ─────────────────────────────────────────────────
            note_id = await upsert_note(
                event.path,
                title,
                event.note_type,
                event.raw_content,
                event.event_type,
            )

            # ── Remove stale embeddings (standard + hierarchical) ─────────────
            old_block_ids = await get_block_ids_for_note(note_id)
            if old_block_ids:
                vector_db.remove_by_block_ids(old_block_ids)
                log.info(
                    "Removed %d stale embeddings for note %d",
                    len(old_block_ids),
                    note_id,
                )
                # Also purge from hierarchical DB
                try:
                    from src.rag.multi_hierarchical import get_hierarchical_db

                    get_hierarchical_db().remove_block_ids(old_block_ids)
                except Exception as exc:
                    log.debug("hier purge failed: %s", exc)

            # ── Insert blocks / tags / tasks ───────────────────────────────────
            block_ids = await insert_blocks(note_id, blocks)

            local_to_db = {local: db_id for local, db_id in enumerate(block_ids)}

            for bt in block_tags:
                bt["block_id"] = local_to_db.get(bt["block_id"])
            for task in tasks:
                task["block_id"] = local_to_db.get(task["block_id"])
            for ref in references:
                ref["source_block_id"] = local_to_db.get(ref["source_block_id"])

            await insert_block_tags(block_ids, block_tags)
            await insert_tasks(note_id, tasks)

            # ── Notify UI immediately (tasks available) ───────────────────────
            try:
                from src.core.queue import ui_update_queue

                await ui_update_queue.put(event)
            except Exception:
                pass

            # ── Background: standard + hierarchical embeddings ─────────────────
            if block_ids and blocks:
                contents = [b["content"] for b in blocks]
                # All blocks share the note title and file path
                file_path = str(event.path)
                titles_list = [title] * len(block_ids)
                paths_list = [file_path] * len(block_ids)

                asyncio.create_task(
                    _generate_embeddings_async(block_ids, contents, note_id)
                )
                asyncio.create_task(
                    _generate_hierarchical_embeddings_async(
                        block_ids, contents, note_id, titles_list, paths_list
                    )
                )

            # ── References ────────────────────────────────────────────────────
            if references:
                resolved = await _resolve_references(references)
                if resolved:
                    await insert_references(note_id, resolved)

            log.info(
                "Processed %s: %s (note_id=%d) – tasks available immediately",
                event.event_type,
                event.path,
                note_id,
            )

        except Exception as exc:
            log.error("Parser worker failed: %s", exc)

        finally:
            if event is not None:
                parser_queue.task_done()
