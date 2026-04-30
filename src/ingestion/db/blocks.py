import datetime

from src.ingestion.db.connection import get_connection


async def get_block_ids_for_note(note_id: int) -> list[int]:
    """Return all existing block IDs for a note (used before deletion)."""
    async with get_connection() as conn:
        cursor = await conn.execute(
            "SELECT id FROM blocks WHERE note_id=?", (note_id,)
        )
        rows = await cursor.fetchall()
        return [row["id"] for row in rows]


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


from typing import Any

async def get_enriched_blocks_data(block_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Fetch enriched block information from database including related block contexts."""
    enriched_data = {}
    async with get_connection() as conn:
        for block_id in block_ids:
            # Join blocks and notes to get file_path and content
            cursor = await conn.execute("""
                SELECT b.id, b.content, b.block_type, b.level, b.parent_block, n.file_path, n.title
                FROM blocks b
                JOIN notes n ON b.note_id = n.id
                WHERE b.id = ?
            """, (block_id,))
            row = await cursor.fetchone()
            
            if not row:
                continue
                
            block_data = dict(row)
            
            # Fetch "Related Blocks" context
            related_blocks = {
                "parent_content": None,
                "children_content": [],
                "tags": [],
                "references": [],
                "referenced_content": []
            }
            
            # 1. Fetch parent content if there is a parent block
            if block_data.get('parent_block'):
                p_cursor = await conn.execute(
                    "SELECT content FROM blocks WHERE id = ?",
                    (block_data['parent_block'],)
                )
                p_row = await p_cursor.fetchone()
                if p_row:
                    related_blocks['parent_content'] = p_row['content']
                    
            # 2. Fetch tags associated with the block
            t_cursor = await conn.execute(
                "SELECT tag FROM block_tags WHERE block_id = ?",
                (block_id,)
            )
            tags = await t_cursor.fetchall()
            related_blocks['tags'] = [t['tag'] for t in tags]
            
            # 3. Fetch references (outbound links) and their content
            r_cursor = await conn.execute("""
                SELECT br.target_title, b.content 
                FROM block_references br
                LEFT JOIN blocks b ON br.target_block_id = b.id
                WHERE br.source_block_id = ?
            """, (block_id,))
            refs = await r_cursor.fetchall()
            related_blocks['references'] = [r['target_title'] for r in refs if r['target_title']]
            related_blocks['referenced_content'] = [r['content'] for r in refs if r['content']]
            
            # 4. Fetch child blocks
            c_cursor = await conn.execute(
                "SELECT content FROM blocks WHERE parent_block = ?",
                (block_id,)
            )
            children = await c_cursor.fetchall()
            related_blocks['children_content'] = [c['content'] for c in children if c['content']]
            
            block_data['related_blocks'] = related_blocks
            enriched_data[block_id] = block_data
            
    return enriched_data
