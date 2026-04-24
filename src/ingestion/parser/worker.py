from typing import List, Dict, Any
from src.core.queue import parser_queue
from src.core.events import ParseEvent
from src.ingestion.db import upsert_note, insert_blocks, insert_tasks, insert_references, get_connection
from src.ingestion.sync_worker import sync_trigger
from src.ingestion.parser.core import parse_markdown
from src.rag.vector_db import add_blocks_to_vector_db

async def _resolve_references(references: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Resolve target_title to target_note_id and optionally target_block_id."""
    resolved = []
    for ref in references:
        target_title = ref['target_title']
        target_block = ref.get('target_block')

        async with get_connection() as conn:
            cursor = await conn.execute(
                "SELECT id FROM notes WHERE title=? AND deleted_at IS NULL",
                (target_title,)
            )
            note_row = await cursor.fetchone()

            if note_row:
                target_note_id = note_row['id']
                target_block_id = None

                if target_block:
                    cursor = await conn.execute(
                        "SELECT id FROM blocks WHERE note_id=? AND content LIKE ?",
                        (target_note_id, f"%{target_block}%")
                    )
                    block_row = await cursor.fetchone()
                    if block_row:
                        target_block_id = block_row['id']

                resolved.append({
                    'source_block_id': ref['source_block_id'],
                    'target_note_id': target_note_id,
                    'target_block_id': target_block_id,
                    'target_title': target_title,
                    'reference_type': ref.get('reference_type', 'link'),
                })

    return resolved

async def parser_worker() -> None:
    """Consumes ParseEvents from parser_queue and processes them."""
    import logging
    from src.rag.vector_db import _get_vector_db
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            event: ParseEvent = await parser_queue.get()
            title, blocks, tasks, references = parse_markdown(event.path, event.raw_content)

            note_id = await upsert_note(event.path, title, event.note_type,
                                        event.raw_content, event.event_type)
            block_ids = await insert_blocks(note_id, blocks)
            await insert_tasks(note_id, tasks)

            # Ensure vector DB is initialized
            try:
                vector_db = _get_vector_db()
                logging.info("Vector DB initialized.")
            except Exception as db_init_exc:
                logging.error(f"Failed to initialize vector DB: {db_init_exc}")
                raise

            # Add blocks to vector database and generate embeddings
            if block_ids and blocks:
                contents = [block['content'] for block in blocks]
                try:
                    await add_blocks_to_vector_db(block_ids, contents)
                    logging.info(f"Embeddings generated and added for note {note_id} ({len(block_ids)} blocks)")
                except Exception as emb_exc:
                    logging.error(f"Failed to generate/add embeddings: {emb_exc}")
                    raise

            if references:
                resolved_refs = await _resolve_references(references)
                if resolved_refs:
                    await insert_references(note_id, resolved_refs)

            sync_trigger.set()
            logging.info(f"Processed {event.event_type}: {event.path} (ID: {note_id})")

        except Exception as e:
            logging.error(f"--> [ERROR] Parser worker failed: {e}")
        finally:
            parser_queue.task_done()

