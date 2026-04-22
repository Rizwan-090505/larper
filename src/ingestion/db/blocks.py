import datetime

from src.ingestion.db.connection import get_connection


async def insert_blocks(note_id: int, blocks: list) -> None:
    """Insert/replace blocks for a note."""
    async with get_connection() as conn:
        await conn.execute("DELETE FROM blocks WHERE note_id=?", (note_id,))

        for block in blocks:
            await conn.execute("""
                INSERT INTO blocks (note_id, block_type, content, level, position, parent_block)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                note_id,
                block['block_type'],
                block['content'],
                block.get('level'),
                block['position'],
                block.get('parent_block'),
            ))

        await conn.commit()
        print(f"--> [DB] Inserted {len(blocks)} blocks for note ID {note_id}")


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
