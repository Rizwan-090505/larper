import datetime

from src.ingestion.db.connection import get_connection


async def insert_blocks(note_id: int, blocks: list) -> list[int]:
    """Insert/replace blocks for a note. Returns list of inserted block IDs.

    blocks[i]['parent_block'] is a parser-local index (0, 1, 2…).
    We remap it to the real SQLite rowid as we insert each block, so the
    FOREIGN KEY(parent_block) REFERENCES blocks(id) constraint is satisfied.
    """
    async with get_connection() as conn:
        await conn.execute("DELETE FROM blocks WHERE note_id=?", (note_id,))

        block_ids = []
        local_to_db: dict[int, int] = {}  # local index → real rowid

        for local_idx, block in enumerate(blocks):
            local_parent = block.get('parent_block')
            db_parent = local_to_db.get(local_parent) if local_parent is not None else None

            cursor = await conn.execute("""
                INSERT INTO blocks (note_id, block_type, content, level, position, parent_block)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                note_id,
                block['block_type'],
                block['content'],
                block.get('level'),
                block['position'],
                db_parent,
            ))
            db_id = cursor.lastrowid
            block_ids.append(db_id)
            local_to_db[local_idx] = db_id

        await conn.commit()
        print(f"--> [DB] Inserted {len(blocks)} blocks for note ID {note_id}")
        return block_ids


async def insert_references(note_id: int, block_references: list) -> None:
    """Insert block references/links into the block_references table."""
    now = datetime.datetime.utcnow().isoformat()

    async with get_connection() as conn:
        # Delete existing references for this note's blocks
        await conn.execute("""
            DELETE FROM block_references
            WHERE source_block_id IN (
                SELECT id FROM blocks WHERE note_id=?
            )
        """, (note_id,))

        for ref in block_references:
            await conn.execute("""
                INSERT INTO block_references
                    (source_block_id, target_note_id, target_block_id,
                     reference_type, target_title, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                ref['source_block_id'],
                ref['target_note_id'],
                ref.get('target_block_id'),
                ref.get('reference_type', 'link'),
                ref.get('target_title'),
                now,
            ))

        await conn.commit()
        print(f"--> [DB] Inserted {len(block_references)} references for note {note_id}")
